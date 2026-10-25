"""match_tender job: reverse funnel for a newly indexed tender -> closest confirmed profiles."""

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from core.matching.funnel import match_tender

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    tender_id = int(payload["tender_id"])
    results = await match_tender(session, tender_id)
    log.info("match_tender_done", tender_id=tender_id, orgs=len(results))
