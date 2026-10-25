from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.agent.chat import answer
from core.llm.claude import CallContext
from core.llm.embeddings import embed, to_pgvector

SM = async_sessionmaker[AsyncSession]


class StreamingFake:
    def __init__(self) -> None:
        self.round = 0
        self.ids: dict[str, int] = {}

    async def stream(self, ctx: Any, **kw: Any) -> AsyncIterator[tuple[str, Any]]:
        self.round += 1
        if self.round == 1:
            block = SimpleNamespace(
                type="tool_use", id="t1", name="search_clauses", input={"query": "earnest money"}
            )
            yield "final", SimpleNamespace(stop_reason="tool_use", content=[block])
            return
        # Clause "emd" was returned by search; "other" exists but was never read; 999 is fake.
        reply = (
            f"EMD is Rs 55,382 [C:{self.ids['emd']}]. MSEs are exempt "
            f"[C:{self.ids['other']}][C:999]."
        )
        for piece in (reply[:20], reply[20:]):
            yield "text", piece
        yield (
            "final",
            SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=reply)]
            ),
        )


@pytest.mark.slow
async def test_chat_keeps_only_citations_the_model_read(sessionmaker: SM, portal_id: int) -> None:
    fake = StreamingFake()
    async with sessionmaker() as s, s.begin():
        tid = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, closes_at) "
                    "VALUES (:p, 'T', 'Lights', 'indexed', now() + interval '3 days') RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
        did = (
            await s.execute(
                text(
                    "INSERT INTO tender_documents (tender_id, storage_key, sha256) VALUES (:t, 'k', 'c') "
                    "RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar_one()
        bodies = {
            "emd": "Earnest money deposit of Rs 55,382 shall be paid online.",
            "other": "Completion period is twelve months from the award.",
        }
        vecs = await embed(list(bodies.values()))
        for (key, body), v in zip(bodies.items(), vecs, strict=True):
            fake.ids[key] = (
                await s.execute(
                    text(
                        "INSERT INTO clauses (document_id, tender_id, page_start, page_end, text, "
                        "embedding) VALUES (:d, :t, 1, 1, :b, CAST(:v AS vector)) RETURNING id"
                    ),
                    {"d": did, "t": tid, "b": body, "v": to_pgvector(v)},
                )
            ).scalar_one()

    async with sessionmaker() as s:
        events = [
            e
            async for e in answer(
                s,
                fake,
                tid,
                "What is the EMD?",
                [],  # type: ignore[arg-type]
                CallContext(purpose="chat"),
            )
        ]
    done = events[-1]
    assert done["type"] == "done"
    # Search returns both clauses here (tiny tender), so "other" counts as read; 999 never does.
    assert fake.ids["emd"] in done["cited"] and 999 not in done["cited"]
    assert "[C:999]" not in done["text"]
    assert any(e["type"] == "token" for e in events)


async def test_chat_on_closed_tender_errors(sessionmaker: SM, portal_id: int) -> None:
    async with sessionmaker() as s:
        events = [
            e
            async for e in answer(
                s,
                StreamingFake(),
                12345,
                "hi",
                [],  # type: ignore[arg-type]
                CallContext(purpose="chat"),
            )
        ]
    assert events == [{"type": "error", "message": "This tender is no longer open."}]
