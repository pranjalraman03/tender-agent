"""Tests run against a real Postgres (infra/docker-compose.yml), in a separate
`<db>_test` database that is recreated and migrated once per test session."""

from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings

TRUNCATE = """
    TRUNCATE jobs, matches, eligibility_reports, chat_messages, company_profiles, users, orgs,
             tender_events, clauses, tender_documents, tenders, portals RESTART IDENTITY CASCADE
"""


def _test_url() -> str:
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    test_url = _test_url()
    db_name = make_url(test_url).database
    admin = create_async_engine(get_settings().database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin.dispose()

    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = test_url
    # Alembic's env.py calls asyncio.run(), so run it outside this event loop.
    import asyncio

    await asyncio.to_thread(command.upgrade, cfg, "head")

    eng = create_async_engine(test_url)
    async with eng.begin() as conn:
        # Non-superuser role so RLS tests are meaningful (superusers bypass RLS).
        await conn.execute(
            text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tender_app_test') THEN
                CREATE ROLE tender_app_test NOLOGIN NOSUPERUSER NOBYPASSRLS;
              END IF;
            END $$
        """)
        )
        await conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                "IN SCHEMA public TO tender_app_test"
            )
        )
        await conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tender_app_test")
        )
    yield eng
    await eng.dispose()


@pytest.fixture
async def sessionmaker(engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with engine.begin() as conn:
        await conn.execute(text(TRUNCATE))
    yield async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def portal_id(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as s, s.begin():
        return int(
            (
                await s.execute(
                    text(
                        "INSERT INTO portals (name, base_url) "
                        "VALUES ('test', 'https://example.org') RETURNING id"
                    )
                )
            ).scalar_one()
        )
