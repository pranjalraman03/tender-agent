import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.jobs import index

SM = async_sessionmaker[AsyncSession]


class FakeClaude:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def create(self, ctx: Any, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append(kwargs)
        block = SimpleNamespace(type="text", text=json.dumps(self.payload))
        return SimpleNamespace(content=[block]), None


async def _setup(sm: SM, portal_id: int) -> int:
    async with sm() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO industries VALUES ('electrical_works', 'Electrical') "
                "ON CONFLICT DO NOTHING"
            )
        )
        tid = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, closes_at) "
                    "VALUES (:p, 'T', 'Street light maintenance', 'parsed', now() + interval '5 days') "
                    "RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
        did = (
            await s.execute(
                text(
                    "INSERT INTO tender_documents (tender_id, storage_key, sha256, parsed_at) "
                    "VALUES (:t, 'k', 'sha1', now()) RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO clauses (document_id, tender_id, clause_no, page_start, page_end, text) "
                "VALUES (:d, :t, '1', 1, 1, 'Maintenance of street lights in Dwarka, Delhi.')"
            ),
            {"d": did, "t": tid},
        )
    return int(tid)


@pytest.mark.slow
async def test_index_marks_indexed_and_rejects_unknown_labels(
    sessionmaker: SM, portal_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid = await _setup(sessionmaker, portal_id)
    fake = FakeClaude(
        {
            "industries": ["electrical_works", "space_travel"],
            "work_state": "Delhi",
            "is_central": True,
            "value_inr": 2769088,
            "emd_inr": 55382,
            "summary": "Street light maintenance in Dwarka, Delhi.",
        }
    )
    monkeypatch.setattr(index, "get_claude", lambda: fake)

    for _ in range(2):  # idempotent
        async with sessionmaker() as s, s.begin():
            await index.handle({"tender_id": tid}, s)

    async with sessionmaker() as s:
        t = (await s.execute(text("SELECT * FROM tenders WHERE id = :t"), {"t": tid})).one()
        live = (await s.execute(text("SELECT count(*) FROM live_tenders"))).scalar_one()
        events = (await s.execute(text("SELECT kind FROM tender_events"))).scalars().all()
        jobs = (await s.execute(text("SELECT kind FROM jobs"))).scalars().all()
        embedded = (
            await s.execute(text("SELECT count(*) FROM clauses WHERE embedding IS NOT NULL"))
        ).scalar_one()
    assert t.pipeline_status == "indexed" and t.industries == ["electrical_works"]
    assert t.work_state == "Delhi" and t.is_central and t.scope_embedding is not None
    assert live == 1 and events == ["published"] and jobs == ["match_tender"]
    assert embedded == 1
    # The tender text is passed as untrusted data, with the allowed labels in the schema.
    user_msg = fake.calls[0]["messages"][0]["content"]
    assert "<untrusted_data" in user_msg
    enum = fake.calls[0]["output_schema"]["properties"]["industries"]["items"]["enum"]
    assert "electrical_works" in enum
