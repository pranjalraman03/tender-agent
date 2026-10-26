import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from core.llm.openai_compat import OpenAICompatClient, extract_json, to_openai_messages


def test_message_conversion_round_trip() -> None:
    assistant_blocks = [
        SimpleNamespace(type="text", text="Let me check."),
        SimpleNamespace(type="tool_use", id="call_1", name="get_clause", input={"clause_id": 7}),
    ]
    msgs = to_openai_messages(
        [{"type": "text", "text": "SYSTEM"}],
        [
            {"role": "user", "content": "Q?"},
            {"role": "assistant", "content": assistant_blocks},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "clause text"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_2",
                        "content": "bad",
                        "is_error": True,
                    },
                ],
            },
        ],
        json_instruction="Reply JSON.",
    )
    assert msgs[0] == {"role": "system", "content": "SYSTEM\n\nReply JSON."}
    assert msgs[2]["tool_calls"][0]["function"] == {
        "name": "get_clause",
        "arguments": '{"clause_id": 7}',
    }
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "clause text"}
    assert msgs[4]["content"] == "ERROR: bad"


def test_extract_json() -> None:
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('{"a": {"b": 2}}') == '{"a": {"b": 2}}'


def _client(handler: Any) -> OpenAICompatClient:
    return OpenAICompatClient("https://llm.test/v1", "key", transport=httpx.MockTransport(handler))


async def test_tool_call_response_becomes_tool_use_block() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "compare_numeric",
                                        "arguments": '{"requirement": "50 lakh", "actual": "62 lakh", "rule": ">="}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    tool = {"name": "compare_numeric", "description": "d", "input_schema": {"type": "object"}}
    msg = await _client(handler).create(
        model="openai/gpt-oss-120b",
        max_tokens=100,
        system=[{"type": "text", "text": "S"}],
        messages=[{"role": "user", "content": "go"}],
        tools=[tool],
        output_config={"effort": "xhigh", "format": {"type": "json_schema", "schema": {}}},
    )
    assert msg.stop_reason == "tool_use"
    assert msg.content[0].input["rule"] == ">=" and msg.usage.input_tokens == 120
    body = seen[0]
    # With tools, the schema goes in the prompt (Groq can't combine tools + response_format).
    assert "response_format" not in body and "JSON schema" in body["messages"][0]["content"]
    assert (
        body["reasoning_effort"] == "high"
        and body["tools"][0]["function"]["name"] == "compare_numeric"
    )


async def test_structured_output_without_tools_uses_strict_schema() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"supported": true, "reason": "ok"}'},
                    }
                ],
                "usage": {},
            },
        )

    msg = await _client(handler).create(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        system="S",
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": {"type": "object"}},
        },
    )
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    assert msg.stop_reason == "end_turn" and json.loads(msg.content[0].text)["supported"]


async def test_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("core.llm.openai_compat.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"}, text="slow down")
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]}
        )

    msg = await _client(handler).create(model="m", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 2 and msg.content[0].text == "hi"


async def test_recovers_answer_sent_as_pseudo_tool_call() -> None:
    generation = json.dumps({"name": "JSON", "arguments": {"findings": [{"criterion_id": "C1"}]}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "tool_use_failed",
                    "message": "attempted to call tool 'JSON'",
                    "failed_generation": generation,
                }
            },
        )

    tool = {"name": "search_clauses", "description": "d", "input_schema": {"type": "object"}}
    msg = await _client(handler).create(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
        output_config={"format": {"type": "json_schema", "schema": {}}},
    )
    assert msg.stop_reason == "end_turn"
    assert json.loads(msg.content[0].text)["findings"][0]["criterion_id"] == "C1"


async def test_bad_call_to_a_real_tool_still_raises() -> None:
    from core.llm.openai_compat import CompatAPIError

    generation = json.dumps({"name": "search_clauses", "arguments": "not-an-object"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "tool_use_failed", "failed_generation": generation}}
        )

    tool = {"name": "search_clauses", "description": "d", "input_schema": {"type": "object"}}
    with pytest.raises(CompatAPIError):
        await _client(handler).create(
            model="m", messages=[{"role": "user", "content": "x"}], tools=[tool]
        )


async def test_output_parse_failure_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "output_parse_failed",
                        "failed_generation": "We need check...",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"supported": true, "reason": "ok"}'},
                    }
                ]
            },
        )

    msg = await _client(handler).create(
        model="m",
        messages=[{"role": "user", "content": "x"}],
        output_config={"format": {"type": "json_schema", "schema": {"type": "object"}}},
    )
    assert calls["n"] == 2 and json.loads(msg.content[0].text)["supported"] is True


async def test_output_parse_failure_gives_up_after_three_tries() -> None:
    from core.llm.openai_compat import CompatAPIError

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"code": "output_parse_failed"}})

    with pytest.raises(CompatAPIError):
        await _client(handler).create(model="m", messages=[{"role": "user", "content": "x"}])
    assert calls["n"] == 3
