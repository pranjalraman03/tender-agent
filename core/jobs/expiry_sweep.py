"""expiry_sweep job: close tenders whose deadline has passed and cancel their queued jobs.
The live_tenders view already hides them; this keeps the data and the queue tidy."""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    closed = (
        await session.execute(
            text("""
            UPDATE tenders SET lifecycle_status = 'closed', updated_at = now()
            WHERE lifecycle_status IN ('open', 'extended') AND closes_at <= now()
            RETURNING id, closes_at
        """)
        )
    ).all()
    cancelled = 0
    for t in closed:
        await session.execute(
            text(
                "INSERT INTO tender_events (tender_id, kind, new_value) "
                "VALUES (:t, 'closed', jsonb_build_object('closes_at', CAST(:c AS text)))"
            ),
            {"t": t.id, "c": str(t.closes_at)},
        )
        cancelled += await queue.cancel_for_tender(session, t.id)
    log.info("expiry_sweep_done", closed=len(closed), jobs_cancelled=cancelled)
