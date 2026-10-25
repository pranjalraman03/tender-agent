"""auth schema for Auth.js (Next.js sign-in): users, accounts, sessions, verification_token

Kept in its own schema so it can't collide with the app's `users` table. The web app's
pg pool sets search_path=auth. The app links Auth.js identities to its own users by email.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA auth")
    op.execute("""
        CREATE TABLE auth.verification_token (
            identifier TEXT NOT NULL,
            expires    TIMESTAMPTZ NOT NULL,
            token      TEXT NOT NULL,
            PRIMARY KEY (identifier, token)
        )
    """)
    op.execute("""
        CREATE TABLE auth.users (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(255),
            email           VARCHAR(255) UNIQUE,
            "emailVerified" TIMESTAMPTZ,
            image           TEXT
        )
    """)
    op.execute("""
        CREATE TABLE auth.accounts (
            id                  SERIAL PRIMARY KEY,
            "userId"            INTEGER NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            type                VARCHAR(255) NOT NULL,
            provider            VARCHAR(255) NOT NULL,
            "providerAccountId" VARCHAR(255) NOT NULL,
            refresh_token       TEXT,
            access_token        TEXT,
            expires_at          BIGINT,
            id_token            TEXT,
            scope               TEXT,
            session_state       TEXT,
            token_type          TEXT,
            UNIQUE (provider, "providerAccountId")
        )
    """)
    op.execute("""
        CREATE TABLE auth.sessions (
            id             SERIAL PRIMARY KEY,
            "userId"       INTEGER NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            expires        TIMESTAMPTZ NOT NULL,
            "sessionToken" VARCHAR(255) NOT NULL UNIQUE
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA auth CASCADE")
