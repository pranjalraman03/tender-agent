import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.jobs import digest, digest_org

SM = async_sessionmaker[AsyncSession]


async def test_digest_sends_live_matches_once(
    sessionmaker: SM, portal_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send(to: str, subject: str, html_body: str, text_body: str) -> str:
        sent.append({"to": to, "subject": subject, "text": text_body})
        return "id"

    monkeypatch.setattr(digest_org, "send_email", fake_send)
    org = uuid.uuid4()
    async with sessionmaker() as s, s.begin():
        await s.execute(text("INSERT INTO orgs (id, name) VALUES (:o, 'Brightline')"), {"o": org})
        await s.execute(
            text("INSERT INTO users (org_id, email) VALUES (:o, 'a@b.test')"), {"o": org}
        )
        for ref, status, fit in [
            ("live", "open", "good"),
            ("closed", "closed", "good"),
            ("poor", "open", "not_eligible"),
        ]:
            tid = (
                await s.execute(
                    text(
                        "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, "
                        "lifecycle_status, closes_at) VALUES (:p, :r, :r, 'indexed', :st, "
                        "now() + interval '3 days') RETURNING id"
                    ),
                    {"p": portal_id, "r": ref, "st": status},
                )
            ).scalar_one()
            await s.execute(
                text(
                    "INSERT INTO matches (org_id, tender_id, stage, fit) "
                    "VALUES (:o, :t, 'agent_checked', :f)"
                ),
                {"o": org, "t": tid, "f": fit},
            )

    for _ in range(2):
        async with sessionmaker() as s, s.begin():
            await digest.handle({"date": "2026-10-25"}, s)
            jobs = (
                (
                    await s.execute(
                        text(
                            "SELECT payload FROM jobs WHERE kind = 'digest_org' "
                            "AND status = 'queued'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            for payload in jobs:
                await digest_org.handle(payload, s)
                await s.execute(text("UPDATE jobs SET status = 'done' WHERE kind = 'digest_org'"))

    assert len(sent) == 1 and sent[0]["to"] == "a@b.test"
    assert "live" in sent[0]["text"] and "closed" not in sent[0]["text"]
    assert sent[0]["subject"] == "1 new tender for Brightline"
