"""Demo data is admin-only: tenders.is_demo, orgs.is_demo, live_tenders excludes demo

live_tenders (used by every user-facing query) now excludes demo tenders, so demo data can't
leak through a forgotten filter. live_tenders_incl_demo is the same rule including demo
tenders; it is read only for admins and the demo company.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenders ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE orgs ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT false")
    op.execute("DROP VIEW live_tenders")
    op.execute("""
        CREATE VIEW live_tenders AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
            AND NOT is_demo
    """)
    op.execute("""
        CREATE VIEW live_tenders_incl_demo AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
    """)


def downgrade() -> None:
    op.execute("DROP VIEW live_tenders_incl_demo")
    op.execute("DROP VIEW live_tenders")
    op.execute("ALTER TABLE orgs DROP COLUMN is_demo")
    op.execute("ALTER TABLE tenders DROP COLUMN is_demo")
    op.execute("""
        CREATE VIEW live_tenders AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
    """)
