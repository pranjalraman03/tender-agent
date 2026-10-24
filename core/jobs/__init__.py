"""Job handler registry. One module per kind in core/jobs/<kind>.py exposing `handle`.

Handlers receive the job payload and a session whose transaction is already in system
context. They must not commit: the worker commits the handler's writes together with
`status = 'done'`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]

# Filled in as job kinds are implemented, e.g. {"crawl": crawl.handle}.
HANDLERS: dict[str, Handler] = {}


class UnknownJobKind(Exception):
    pass


def get_handler(kind: str) -> Handler:
    try:
        return HANDLERS[kind]
    except KeyError:
        raise UnknownJobKind(kind) from None
