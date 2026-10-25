"""Worker process: claims jobs from the `jobs` table and runs them."""

import asyncio
import signal

import structlog

from core.config import get_settings
from core.db.session import get_sessionmaker
from core.observability import configure_logging, init_sentry
from core.queue.worker import run_once

log = structlog.get_logger()


async def main() -> None:
    configure_logging(json_logs=get_settings().app_env == "production")
    init_sentry("worker")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    sessionmaker = get_sessionmaker()
    poll = get_settings().worker_poll_interval_s
    log.info("worker_started")
    while not stop.is_set():
        try:
            did_work = await run_once(sessionmaker)
        except Exception:
            # DB unreachable etc. Log and back off; the job itself is not lost.
            log.exception("worker_iteration_error")
            did_work = False
        if not did_work:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll)
            except TimeoutError:
                pass
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
