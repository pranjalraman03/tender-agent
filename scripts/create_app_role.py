"""Create / update the application's database role (run as the owner, after migrations).

The API, worker, scheduler and web app must connect as a NON-superuser role: superusers and
BYPASSRLS roles skip row-level security, so tenant isolation would silently stop applying
(ADR 0003). Migrations keep running as the owner role.

    DATABASE_URL=<owner url> APP_DB_PASSWORD=<secret> python scripts/create_app_role.py

Idempotent: safe to run on every deploy (re-grants on tables added by new migrations).
"""

import asyncio
import os
import sys

from sqlalchemy import text

from core.db.session import get_engine

# Schemas the app uses: public (app data) and auth (Auth.js sign-in tables).
GRANTS = (
    "GRANT USAGE ON SCHEMA public, auth TO tender_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public, auth TO tender_app",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public, auth TO tender_app",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public, auth "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tender_app",
    "ALTER DEFAULT PRIVILEGES IN SCHEMA public, auth "
    "GRANT USAGE, SELECT ON SEQUENCES TO tender_app",
)


async def main() -> None:
    password = os.environ.get("APP_DB_PASSWORD", "")
    if len(password) < 16:
        sys.exit("APP_DB_PASSWORD must be set to at least 16 characters")
    async with get_engine().begin() as conn:
        await conn.execute(
            text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tender_app') THEN
                CREATE ROLE tender_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
              END IF;
            END $$
        """)
        )
        # Password via a bound parameter + format(%L) quoting; never string-built.
        await conn.execute(
            text("SELECT set_config('app.new_role_password', :p, true)"), {"p": password}
        )
        await conn.execute(
            text("""
            DO $$ BEGIN
              EXECUTE format('ALTER ROLE tender_app PASSWORD %L',
                             current_setting('app.new_role_password'));
            END $$
        """)
        )
        for stmt in GRANTS:
            await conn.execute(text(stmt))
    await get_engine().dispose()
    print("role tender_app ready (schemas: public, auth)")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
