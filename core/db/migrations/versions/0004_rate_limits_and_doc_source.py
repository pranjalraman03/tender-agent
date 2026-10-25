"""rate_limits table; tender_documents.source / uploaded_by; users.name

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fixed-window counters; old windows are deleted opportunistically by the app.
    op.execute("""
        CREATE TABLE rate_limits (
            bucket       TEXT NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            count        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bucket, window_start)
        )
    """)
    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN source TEXT NOT NULL DEFAULT 'crawler' "
        "CHECK (source IN ('crawler', 'admin', 'user'))"
    )
    op.execute(
        "ALTER TABLE tender_documents ADD COLUMN uploaded_by UUID REFERENCES users(id) "
        "ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE users ADD COLUMN name TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN name")
    op.execute("ALTER TABLE tender_documents DROP COLUMN uploaded_by")
    op.execute("ALTER TABLE tender_documents DROP COLUMN source")
    op.execute("DROP TABLE rate_limits")
