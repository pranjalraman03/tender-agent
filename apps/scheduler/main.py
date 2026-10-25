"""Scheduler process: only enqueues jobs (and requeues stuck ones). Never does the work.

Every scheduled job has a time-bucketed idempotency key, so a scheduler restart (or two
schedulers running by mistake) can't enqueue the same run twice."""

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core import queue
from core.config import get_settings
from core.db.session import system_transaction
from core.observability import configure_logging

log = structlog.get_logger()
IST = ZoneInfo("Asia/Kolkata")
PORTALS = ["cppp"]


async def requeue_stuck_jobs() -> None:
    async with system_transaction() as session:
        n = await queue.requeue_stuck(session, get_settings().job_timeouts_s)
    if n:
        log.warning("requeued_stuck_jobs", count=n)


async def enqueue(kind: str, payload: dict[str, str], bucket_format: str) -> None:
    bucket = datetime.now(UTC).astimezone(IST).strftime(bucket_format)
    suffix = ":".join(payload.values())
    key = f"{kind}:{suffix}:{bucket}" if suffix else f"{kind}:{bucket}"
    async with system_transaction() as session:
        await queue.enqueue(session, kind, payload, key)


async def main() -> None:
    configure_logging(json_logs=get_settings().app_env == "production")
    scheduler = AsyncIOScheduler(timezone=IST)
    now = datetime.now(IST)
    scheduler.add_job(requeue_stuck_jobs, "interval", minutes=1, id="requeue_stuck")
    for portal in PORTALS:
        # crawl every 6 h (bucket = date + 6-hour block), first run immediately
        scheduler.add_job(
            enqueue,
            "interval",
            hours=6,
            next_run_time=now,
            id=f"crawl_{portal}",
            args=["crawl", {"portal": portal}, "%Y-%m-%dT%H"],
        )
        scheduler.add_job(
            enqueue,
            "cron",
            minute=20,
            id=f"recheck_{portal}",
            args=["recheck", {"portal": portal}, "%Y-%m-%dT%H"],
        )
    scheduler.add_job(
        enqueue, "cron", minute=5, id="expiry_sweep", args=["expiry_sweep", {}, "%Y-%m-%dT%H"]
    )
    scheduler.add_job(
        enqueue,
        "cron",
        hour=8,
        minute=0,
        id="digest",  # 08:00 IST
        args=["digest", {}, "%Y-%m-%d"],
    )
    scheduler.start()
    log.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
