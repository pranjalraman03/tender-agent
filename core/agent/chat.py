"""Per-tender chat: streamed answers that cite clauses as [C:<clause_id>].

The model's only tool is search over this tender's clauses. After the answer completes,
cited ids are checked against the tender: unknown ids are removed from the text, and the
validated ids are returned for the UI to link to the PDF page."""

import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.claude import UNTRUSTED_NOTE, CallContext, Claude, tool_result_json, wrap_untrusted
from core.search.hybrid import search_clauses

PROMPT_VERSION = "chat_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
CITATION = re.compile(r"\[C:(\d+)\]")
MAX_TOOL_ROUNDS = 4
HISTORY_TURNS = 6

SEARCH_TOOL = {
    "name": "search_clauses",
    "description": "Search this tender's clauses. Returns clause ids, numbers, pages, text.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
}


async def tender_brief(session: AsyncSession, tender_id: int) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, title, org_name, value_inr, emd_inr, closes_at, work_state, "
                    "summary FROM live_tenders WHERE id = :t"
                ),
                {"t": tender_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return {k: str(v) if v is not None else None for k, v in row.items()} if row else None


async def answer(
    session: AsyncSession,
    claude: Claude,
    tender_id: int,
    question: str,
    history: list[dict[str, str]],
    ctx: CallContext,
) -> AsyncIterator[dict[str, Any]]:
    """Yields {"type": "token", "text"} events, then {"type": "done", "text", "cited"}."""
    brief = await tender_brief(session, tender_id)
    if brief is None:
        yield {"type": "error", "message": "This tender is no longer open."}
        return
    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": m["content"]} for m in history[-HISTORY_TURNS:]
    ]
    messages.append(
        {
            "role": "user",
            "content": (
                wrap_untrusted("tender_fields", json.dumps(brief, ensure_ascii=False))
                + f"\n\nQuestion: {question}"
            ),
        }
    )
    seen: set[int] = set()
    full_text = ""
    for _round in range(MAX_TOOL_ROUNDS + 1):
        final = None
        async for kind, value in claude.stream(
            ctx,
            tier="fast",
            system=PROMPT + "\n\n" + UNTRUSTED_NOTE,
            messages=messages,
            max_tokens=4000,
            effort="low",
            tools=[SEARCH_TOOL],
        ):
            if kind == "text":
                full_text += value
                yield {"type": "token", "text": value}
            elif kind == "final":
                final = value
        assert final is not None
        messages.append({"role": "assistant", "content": final.content})
        if final.stop_reason != "tool_use":
            break
        results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            hits = await search_clauses(session, tender_id, str(block.input.get("query", "")), k=5)
            seen.update(h.clause_id for h in hits)
            payload = [
                {
                    "clause_id": h.clause_id,
                    "clause_no": h.clause_no,
                    "pages": f"{h.page_start}-{h.page_end}",
                    "text": h.text[:2000],
                }
                for h in hits
            ]
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": wrap_untrusted("search_clauses", tool_result_json(payload)),
                }
            )
        messages.append({"role": "user", "content": results})
        full_text += "\n\n"
        yield {"type": "token", "text": "\n\n"}

    cited = [int(i) for i in dict.fromkeys(CITATION.findall(full_text))]
    valid = (
        set(
            (
                await session.execute(
                    text("SELECT id FROM clauses WHERE tender_id = :t AND id = ANY(:ids)"),
                    {"t": tender_id, "ids": cited},
                )
            ).scalars()
        )
        if cited
        else set()
    )
    # Only clauses the model actually read in this answer, and that belong to the tender.
    valid &= seen
    clean = CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", full_text)
    yield {"type": "done", "text": clean.strip(), "cited": [i for i in cited if i in valid]}


async def save_turn(
    session: AsyncSession,
    session_id: uuid.UUID,
    org_id: uuid.UUID | None,
    tender_id: int,
    question: str,
    answer_text: str,
    cited: list[int],
) -> None:
    for role, content, ids in (("user", question, []), ("assistant", answer_text, cited)):
        await session.execute(
            text(
                "INSERT INTO chat_messages (session_id, org_id, tender_id, role, content, "
                "cited_clause_ids) VALUES (:s, :o, :t, :r, :c, :ids)"
            ),
            {"s": session_id, "o": org_id, "t": tender_id, "r": role, "c": content, "ids": ids},
        )
