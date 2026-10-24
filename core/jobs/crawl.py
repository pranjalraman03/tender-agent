"""crawl job: read a portal's listing, insert new tenders as `discovered`, enqueue download.

CPPP's public listing is only ~10 rows and gives no portal-unique id, so every row's detail
page is fetched and new tenders are detected by the (portal_id, tender_ref) unique key.
"""

from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.config import get_settings
from core.crawlers.base import Crawler, CrawlError, TenderDetail
from core.crawlers.cppp import CpppCrawler

log = structlog.get_logger()


def build_crawler(portal: str, client: httpx.AsyncClient, cfg: dict[str, Any]) -> Crawler:
    if portal == "cppp":
        return CpppCrawler(client, min_interval_s=float(cfg.get("min_interval_s", 3)))
    raise CrawlError(f"no crawler for portal {portal!r}")


async def insert_tender(session: AsyncSession, portal_id: int, d: TenderDetail) -> int | None:
    """Insert a newly discovered tender. Returns its id, or None if it was already known."""
    result = await session.execute(
        text("""
            INSERT INTO tenders (portal_id, tender_ref, title, org_name, value_inr, emd_inr,
                                 published_at, closes_at, source_url, pipeline_status)
            VALUES (:portal_id, :ref, :title, :org, :value, :emd, :published, :closes,
                    :url, 'discovered')
            ON CONFLICT (portal_id, tender_ref) DO NOTHING
            RETURNING id
        """),
        {
            "portal_id": portal_id,
            "ref": d.tender_ref,
            "title": d.title,
            "org": d.org_name,
            "value": d.value_inr,
            "emd": d.emd_inr,
            "published": d.published_at,
            "closes": d.closes_at,
            "url": d.source_url,
        },
    )
    return result.scalar_one_or_none()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    portal_name = str(payload["portal"])
    portal = (
        await session.execute(
            text("SELECT id, crawl_cfg FROM portals WHERE name = :name"), {"name": portal_name}
        )
    ).one_or_none()
    if portal is None:
        raise CrawlError(f"unknown portal {portal_name!r}; run scripts/seed.py")
    cfg: dict[str, Any] = portal.crawl_cfg
    max_details = int(cfg.get("max_detail_pages", 20))

    details: list[TenderDetail] = []
    headers = {"User-Agent": get_settings().crawler_user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        crawler = build_crawler(portal_name, client, cfg)
        items = await crawler.list_new()
        for item in items[:max_details]:
            try:
                details.append(await crawler.fetch_detail(item))
            except CrawlError as exc:
                log.warning("detail_skipped", title=item.title[:80], error=str(exc))

    new = 0
    for d in details:
        tender_id = await insert_tender(session, portal.id, d)
        if tender_id is not None:
            new += 1
            await queue.enqueue(
                session, "download", {"tender_id": tender_id}, f"download:{tender_id}"
            )
    log.info("crawl_done", portal=portal_name, listed=len(items), fetched=len(details), new=new)
