"""recheck job: detect corrigenda, extensions and cancellations for tenders we track.

CPPP detail links expire with the portal session and the search pages are captcha-gated,
so a per-tender re-fetch isn't possible. Instead the homepage's public "Latest Corrigendum"
table is matched to our tenders by reference number:
- a new closing date -> closes_at updated, lifecycle 'extended' (if later), 'extended' event;
- every match -> a 'corrigendum' event, so the admin queue asks for the corrigendum PDF
  (whose upload triggers re-indexing and eligibility rechecks).
"""

import json
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.jobs.crawl import build_crawler

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    portal_name = str(payload["portal"])
    portal = (
        await session.execute(
            text("SELECT id, crawl_cfg FROM portals WHERE name = :n"), {"n": portal_name}
        )
    ).one()
    headers = {"User-Agent": get_settings().crawler_user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
        notices = await build_crawler(portal_name, client, portal.crawl_cfg).list_corrigenda()

    matched = extended = 0
    for n in notices:
        tender = (
            await session.execute(
                text("""
                SELECT id, closes_at, lifecycle_status FROM tenders
                WHERE portal_id = :p AND portal_fields->>'Tender Reference Number' = :ref
                  AND lifecycle_status IN ('open', 'extended', 'closed')
            """),
                {"p": portal.id, "ref": n.reference_no},
            )
        ).one_or_none()
        if tender is None:
            continue
        matched += 1
        event = (
            await session.execute(
                text("""
                INSERT INTO tender_events (tender_id, kind, new_value)
                SELECT :t, 'corrigendum', CAST(:v AS jsonb)
                WHERE NOT EXISTS (
                    SELECT 1 FROM tender_events WHERE tender_id = :t AND kind = 'corrigendum'
                      AND new_value->>'title' = :title)
                RETURNING id
            """),
                {
                    "t": tender.id,
                    "title": n.title,
                    "v": json.dumps({"title": n.title, "closes_at": str(n.closes_at)}),
                },
            )
        ).scalar_one_or_none()
        if n.closes_at and tender.closes_at and n.closes_at > tender.closes_at:
            extended += 1
            await session.execute(
                text("""
                    UPDATE tenders SET closes_at = :new, updated_at = now(),
                      lifecycle_status = CASE WHEN lifecycle_status IN ('open', 'closed')
                                              THEN 'extended' ELSE lifecycle_status END
                    WHERE id = :t
                """),
                {"t": tender.id, "new": n.closes_at},
            )
            await session.execute(
                text(
                    "INSERT INTO tender_events (tender_id, kind, old_value, new_value) "
                    "VALUES (:t, 'extended', CAST(:old AS jsonb), CAST(:new AS jsonb))"
                ),
                {
                    "t": tender.id,
                    "old": json.dumps({"closes_at": str(tender.closes_at)}),
                    "new": json.dumps({"closes_at": str(n.closes_at)}),
                },
            )
        if event is not None:
            log.info("corrigendum_detected", tender_id=tender.id, title=n.title)
    await session.execute(
        text(
            "UPDATE tenders SET last_checked_at = now() WHERE portal_id = :p "
            "AND lifecycle_status IN ('open', 'extended')"
        ),
        {"p": portal.id},
    )
    log.info(
        "recheck_done", portal=portal_name, notices=len(notices), matched=matched, extended=extended
    )
