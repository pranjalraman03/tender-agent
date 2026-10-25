import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import queue
from core.crawlers.base import CorrigendumNotice
from core.crawlers.cppp import parse_corrigenda
from core.jobs import expiry_sweep, recheck

SM = async_sessionmaker[AsyncSession]
IST = ZoneInfo("Asia/Kolkata")
FIXTURE = Path(__file__).parent / "crawlers" / "fixtures" / "cppp_home.html"


def test_parse_corrigenda_fixture() -> None:
    notices = parse_corrigenda(FIXTURE.read_text(errors="ignore"))
    assert notices[0].title == "Corrigendum-2 for date extended"
    assert notices[0].reference_no == "02/2026-27 EE PWD NH Division Pali"
    assert notices[0].closes_at == datetime(2026, 11, 2, 11, 0, tzinfo=IST)


async def test_expiry_sweep_closes_and_cancels(sessionmaker: SM, portal_id: int) -> None:
    async with sessionmaker() as s, s.begin():
        past = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, closes_at) "
                    "VALUES (:p, 'old', 't', now() - interval '1 minute') RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO tenders (portal_id, tender_ref, title, closes_at) "
                "VALUES (:p, 'new', 't', now() + interval '1 day')"
            ),
            {"p": portal_id},
        )
        await queue.enqueue(s, "parse", {"tender_id": past}, "parse-old")
    async with sessionmaker() as s, s.begin():
        await expiry_sweep.handle({}, s)
    async with sessionmaker() as s:
        states = dict(
            (await s.execute(text("SELECT tender_ref, lifecycle_status FROM tenders")))
            .tuples()
            .all()
        )
        job = (await s.execute(text("SELECT status FROM jobs"))).scalar_one()
        events = (await s.execute(text("SELECT kind FROM tender_events"))).scalars().all()
    assert states == {"old": "closed", "new": "open"}
    assert job == "cancelled" and events == ["closed"]


async def test_recheck_extends_deadline_and_records_corrigendum(
    sessionmaker: SM, portal_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = datetime(2030, 1, 10, 17, 0, tzinfo=IST)
    new = old + timedelta(days=7)
    async with sessionmaker() as s, s.begin():
        await s.execute(
            text("""
            INSERT INTO tenders (portal_id, tender_ref, title, closes_at, portal_fields)
            VALUES (:p, 'T1', 't', :c, CAST(:f AS jsonb))"""),
            {"p": portal_id, "c": old, "f": json.dumps({"Tender Reference Number": "REF/1"})},
        )

    class Fake:
        async def list_corrigenda(self) -> list[CorrigendumNotice]:
            return [
                CorrigendumNotice("Corrigendum-1 date extended", "REF/1", new),
                CorrigendumNotice("Unrelated", "OTHER", new),
            ]

    def fake_build(*a: Any) -> Fake:
        return Fake()

    monkeypatch.setattr(recheck, "build_crawler", fake_build)
    portal = await _portal_name(sessionmaker, portal_id)
    for _ in range(2):  # idempotent
        async with sessionmaker() as s, s.begin():
            await recheck.handle({"portal": portal}, s)
    async with sessionmaker() as s:
        t = (await s.execute(text("SELECT closes_at, lifecycle_status FROM tenders"))).one()
        kinds = sorted((await s.execute(text("SELECT kind FROM tender_events"))).scalars())
    assert t.closes_at == new and t.lifecycle_status == "extended"
    assert kinds == ["corrigendum", "extended"]


async def _portal_name(sm: SM, portal_id: int) -> str:
    async with sm() as s:
        return str(
            (
                await s.execute(text("SELECT name FROM portals WHERE id = :p"), {"p": portal_id})
            ).scalar_one()
        )
