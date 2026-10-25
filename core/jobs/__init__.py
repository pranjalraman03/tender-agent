"""Job handler registry. One module per kind in core/jobs/<kind>.py exposing `handle`.

Handlers receive the job payload and a session whose transaction is already in system
context. They must not commit: the worker commits the handler's writes together with
`status = 'done'`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[dict[str, Any], AsyncSession], Awaitable[None]]


# kind -> needs the Claude API. Without ANTHROPIC_API_KEY those kinds are not registered,
# so their jobs wait in the queue (instead of failing and dead-lettering) until a key is set.
KINDS: dict[str, bool] = {
    "crawl": False,
    "download": False,
    "parse": False,
    "index": True,
    "fit_check": True,
}


def _registry() -> dict[str, Handler]:
    import importlib

    from core.config import get_settings

    llm_ok = get_settings().llm_configured
    return {
        kind: importlib.import_module(f"core.jobs.{kind}").handle
        for kind, needs_llm in KINDS.items()
        if llm_ok or not needs_llm
    }


# Kinds without a handler yet, or LLM kinds without a key, stay queued: the worker only
# claims kinds listed here.
HANDLERS: dict[str, Handler] = _registry()
