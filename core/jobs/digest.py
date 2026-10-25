"""digest job (daily): fan out one digest_org job per org with new matches. Each org's job
is idempotent per day, so a failure for one org never re-sends anyone else's email."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    day = payload.get("date") or datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
    orgs = (
        (
            await session.execute(
                text("""
        SELECT DISTINCT m.org_id FROM matches m JOIN live_tenders t ON t.id = m.tender_id
        WHERE m.fit IN ('good', 'possible') AND m.notified_at IS NULL
          AND m.user_state IS DISTINCT FROM 'dismissed'
    """)
            )
        )
        .scalars()
        .all()
    )
    for org_id in orgs:
        await queue.enqueue(
            session, "digest_org", {"org_id": str(org_id)}, f"digest_org:{org_id}:{day}"
        )
    log.info("digest_fanout", orgs=len(orgs), date=str(day))
