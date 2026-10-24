"""Scheduler process: only enqueues jobs (and requeues stuck ones). Never does work."""

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import queue
from core.config import get_settings
from core.db.session import system_transaction
from core.observability import configure_logging

log = structlog.get_logger()


async def requeue_stuck_jobs() -> None:
    async with system_transaction() as session:
        n = await queue.requeue_stuck(session, get_settings().job_timeouts_s)
    if n:
        log.warning("requeued_stuck_jobs", count=n)


async def main() -> None:
    configure_logging(json_logs=get_settings().app_env == "production")
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(requeue_stuck_jobs, "interval", minutes=1, id="requeue_stuck")
    # crawl, full_sweep, recheck, expiry_sweep and digest are added as they are built.
    scheduler.start()
    log.info("scheduler_started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
