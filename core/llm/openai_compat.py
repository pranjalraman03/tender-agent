"""OpenAI-compatible chat-completions backend (default: Groq's free tier, open-weight models).

Used for local testing without a Claude API key (LLM_PROVIDER=openai_compat). It accepts the
same request shape the rest of core/llm builds for Claude and returns Claude-shaped results
(content blocks of type "text" / "tool_use", stop_reason "end_turn" / "tool_use" /
"max_tokens", usage.input_tokens / output_tokens), so the agent loop, indexing and chat code
don't need to know which provider is behind them.

Differences handled here:
- tool results become role="tool" messages; tool_use blocks become assistant tool_calls;
- structured output uses response_format json_schema (strict) when no tools are sent; Groq
  doesn't allow it together with tools, so then the schema is given in the system prompt and
  the JSON is extracted from the final text;
- effort maps to reasoning_effort (gpt-oss supports low / medium / high);
- open models sometimes break format: a final answer sent as a call to a made-up tool is
  recovered, and an "output_parse_failed" rejection is retried (up to 3 tries in total);
- streaming is emulated (one chunk), which is fine for local testing.
"""

import asyncio
import json
import re
from types import SimpleNamespace
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4  # transport / 429 / 5xx retries per request
PARSE_FAILURE_ATTEMPTS = 3  # tries when the model output fails the required format
EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class CompatAPIError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"LLM API error {status}: {body[:500]}")
        self.status = status
        self.body = body

    @property
    def code(self) -> str | None:
        """Provider error code, e.g. "tool_use_failed" or "output_parse_failed"."""
        try:
            code = json.loads(self.body)["error"].get("code")
        except (KeyError, TypeError, ValueError, AttributeError):
            return None
        return str(code) if code else None


def recover_pseudo_tool_answer(exc: CompatAPIError, tool_names: set[str]) -> dict[str, Any] | None:
    """Open models sometimes return their final JSON answer as a call to a made-up tool (e.g.
    "JSON"); Groq rejects that with 400 tool_use_failed and includes the generation. If the
    called tool isn't a real one, its arguments are the answer: turn them into a normal final
    message. Anything else is re-raised by the caller."""
    if exc.status != 400:
        return None
    try:
        error = json.loads(exc.body)["error"]
        if error.get("code") != "tool_use_failed":
            return None
        generation = json.loads(error["failed_generation"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(generation, dict) or generation.get("name") in tool_names:
        return None
    arguments = generation.get("arguments")
    if not isinstance(arguments, dict):
        return None
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(arguments)}}],
        "usage": {},
    }


def _get(block: Any, key: str) -> Any:
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(str(_get(b, "text") or "") for b in system or [])


def to_openai_messages(
    system: Any, messages: list[dict[str, Any]], json_instruction: str | None
) -> list[dict[str, Any]]:
    sys_text = _system_text(system)
    if json_instruction:
        sys_text += "\n\n" + json_instruction
    out: list[dict[str, Any]] = [{"role": "system", "content": sys_text}]
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            texts = [str(_get(b, "text")) for b in content if _get(b, "type") == "text"]
            calls = [
                {
                    "id": _get(b, "id"),
                    "type": "function",
                    "function": {
                        "name": _get(b, "name"),
                        "arguments": json.dumps(_get(b, "input") or {}),
                    },
                }
                for b in content
                if _get(b, "type") == "tool_use"
            ]
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        # user turn: tool results and/or text blocks
        texts = []
        for b in content:
            kind = _get(b, "type")
            if kind == "tool_result":
                body = _get(b, "content")
                body = body if isinstance(body, str) else json.dumps(body)
                if _get(b, "is_error"):
                    body = f"ERROR: {body}"
                out.append(
                    {"role": "tool", "tool_call_id": _get(b, "tool_use_id"), "content": body}
                )
            elif kind == "text":
                texts.append(str(_get(b, "text")))
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    return out


def to_openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply (code fences, leading prose)."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return cleaned[start : end + 1] if start != -1 and end > start else cleaned


def to_claude_shape(data: dict[str, Any], json_from_text: bool) -> Any:
    choice = data["choices"][0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    blocks: list[Any] = []
    text = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []
    if text:
        if json_from_text and not tool_calls:
            text = extract_json(text)
        blocks.append(SimpleNamespace(type="text", text=text))
    for call in tool_calls:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_invalid_arguments": fn.get("arguments")}
        blocks.append(
            SimpleNamespace(type="tool_use", id=call.get("id"), name=fn.get("name"), input=args)
        )
    stop = "tool_use" if tool_calls else "max_tokens" if finish == "length" else "end_turn"
    usage = data.get("usage") or {}
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop,
        stop_details=None,
        model=data.get("model"),
        usage=SimpleNamespace(
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


class OpenAICompatClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport

    async def create(self, **kwargs: Any) -> Any:
        """Takes the Claude-style kwargs built by core.llm.claude and returns a Claude-shaped
        message."""
        tools = kwargs.get("tools")
        output_config = kwargs.get("output_config") or {}
        fmt = output_config.get("format")
        json_instruction = None
        body: dict[str, Any] = {
            "model": kwargs["model"],
            "max_completion_tokens": kwargs.get("max_tokens", 8000),
            "reasoning_effort": EFFORT.get(output_config.get("effort", "medium"), "medium"),
        }
        if fmt and not tools:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": fmt["schema"]},
            }
        elif fmt:
            json_instruction = (
                "When you have finished using tools, reply with ONLY a JSON object (no prose, "
                "no code fences) that matches this JSON schema:\n" + json.dumps(fmt["schema"])
            )
        body["messages"] = to_openai_messages(
            kwargs.get("system"), kwargs["messages"], json_instruction
        )
        openai_tools = to_openai_tools(tools)
        if openai_tools:
            body["tools"] = openai_tools
        for attempt in range(1, PARSE_FAILURE_ATTEMPTS + 1):
            try:
                data = await self._post(body)
                break
            except CompatAPIError as exc:
                recovered = recover_pseudo_tool_answer(exc, {t["name"] for t in tools or []})
                if recovered is not None:
                    log.info("llm_recovered_pseudo_tool_answer", model=kwargs["model"])
                    data = recovered
                    break
                # The model's output didn't fit the required format (e.g. reasoning text where
                # strict JSON was required). Sampling varies, so the same request usually
                # succeeds on another try.
                if exc.code == "output_parse_failed" and attempt < PARSE_FAILURE_ATTEMPTS:
                    log.info(
                        "llm_retry_output_parse_failed", model=kwargs["model"], attempt=attempt
                    )
                    continue
                raise
        return to_claude_shape(data, json_from_text=bool(fmt))

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", json=body, headers=headers
                    )
                except httpx.TransportError:
                    if attempt == MAX_ATTEMPTS:
                        raise
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code == 200:
                    data: dict[str, Any] = response.json()
                    return data
                if response.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                    wait = float(response.headers.get("retry-after") or 2**attempt)
                    log.info("llm_retry", status=response.status_code, wait_s=wait)
                    await asyncio.sleep(min(wait, 30))
                    continue
                raise CompatAPIError(response.status_code, response.text)
        raise AssertionError("unreachable")
