"""Job handler registry. One module per kind in core/jobs/<kind>.py exposing `handle`.

Handlers receive the job payload and a session whose transaction is already in system
context. They must not commit: the worker commits the handler's writes together with
`status = 'done'`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]


def _registry() -> dict[str, Handler]:
    from core.jobs import crawl

    return {"crawl": crawl.handle}


# Kinds without a handler yet (e.g. `download` before build step 2) stay queued: the worker
# only claims kinds listed here.
HANDLERS: dict[str, Handler] = _registry()
