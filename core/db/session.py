"""Async engine, session factory and tenant-context helpers.

RLS on tenant tables reads two transaction-local settings:
  app.org_id  - the authenticated user's org (set by the API per request)
  app.role    - 'system' for worker / scheduler / admin / eval code that works across orgs
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def set_org_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Scope the current transaction to one org. Call at the start of each transaction."""
    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"), {"org_id": str(org_id)}
    )


async def set_system_context(session: AsyncSession) -> None:
    """Allow the current transaction to see all orgs (worker, scheduler, admin, evals)."""
    await session.execute(text("SELECT set_config('app.role', 'system', true)"))


@asynccontextmanager
async def system_transaction() -> AsyncIterator[AsyncSession]:
    """One transaction in system context: commits on exit, rolls back on error."""
    async with get_sessionmaker()() as session, session.begin():
        await set_system_context(session)
        yield session
