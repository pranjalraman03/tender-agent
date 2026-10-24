"""One iteration of the worker: claim -> run handler -> complete, or fail."""

import traceback

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import queue
from core.db.session import set_system_context
from core.jobs import Handler, get_handler

log = structlog.get_logger()


async def run_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    handlers: dict[str, Handler] | None = None,
) -> bool:
    """Process at most one job. Returns False if there was nothing to do.

    `handlers` overrides the registry (used by tests).
    """
    async with sessionmaker() as session, session.begin():
        await set_system_context(session)
        job = await queue.claim(session)
    if job is None:
        return False

    with structlog.contextvars.bound_contextvars(
        job_id=job.id, job_kind=job.kind, attempt=job.attempts
    ):
        try:
            handler = handlers[job.kind] if handlers is not None else get_handler(job.kind)
            async with sessionmaker() as session, session.begin():
                await set_system_context(session)
                await handler(job.payload, session)
                await queue.complete(session, job.id)
        except Exception as exc:
            error = "".join(traceback.format_exception(exc))
            async with sessionmaker() as session, session.begin():
                await set_system_context(session)
                status = await queue.fail(session, job, error)
            log.warning("job_failed", new_status=status, error=repr(exc))
        else:
            log.info("job_done")
    return True
