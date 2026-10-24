from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.crawlers.base import ListingItem, TenderDetail
from core.db.session import set_system_context
from core.jobs import crawl

IST = ZoneInfo("Asia/Kolkata")


class FakeCrawler:
    def __init__(self, refs: list[str]) -> None:
        self.refs = refs

    async def list_new(self) -> list[ListingItem]:
        return [ListingItem(r, r, None, f"https://x/{r}") for r in self.refs]

    async def fetch_detail(self, item: ListingItem) -> TenderDetail:
        return TenderDetail(
            tender_ref=item.reference_no,
            title=item.title,
            org_name="Org",
            value_inr=None,
            emd_inr=None,
            published_at=None,
            closes_at=datetime(2030, 1, 1, 17, 0, tzinfo=IST),
            source_url=None,
        )


async def test_crawl_inserts_new_tenders_once_and_enqueues_download(
    sessionmaker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with sessionmaker() as s, s.begin():
        await s.execute(text("INSERT INTO portals (name, base_url) VALUES ('fake', 'https://x')"))

    refs = ["A", "B"]

    def fake_build(portal: str, client: httpx.AsyncClient, cfg: dict[str, Any]) -> FakeCrawler:
        return FakeCrawler(refs)

    monkeypatch.setattr(crawl, "build_crawler", fake_build)

    for _ in range(2):  # second run must not duplicate anything
        async with sessionmaker() as s, s.begin():
            await set_system_context(s)
            await crawl.handle({"portal": "fake"}, s)
    refs.append("C")
    async with sessionmaker() as s, s.begin():
        await crawl.handle({"portal": "fake"}, s)

    async with sessionmaker() as s:
        tenders = (
            await s.execute(
                text("SELECT tender_ref, pipeline_status FROM tenders ORDER BY tender_ref")
            )
        ).all()
        jobs = (await s.execute(text("SELECT kind, count(*) FROM jobs GROUP BY kind"))).all()
    assert [(t.tender_ref, t.pipeline_status) for t in tenders] == [
        ("A", "discovered"),
        ("B", "discovered"),
        ("C", "discovered"),
    ]
    assert [(j.kind, j.count) for j in jobs] == [("download", 3)]
