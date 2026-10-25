"""tenders.portal_fields + summary, tender_documents.filename, llm_calls.trace_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive and defaulted, so existing rows and code keep working.
    op.execute("ALTER TABLE tenders ADD COLUMN portal_fields JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE tenders ADD COLUMN summary TEXT")
    op.execute("ALTER TABLE tender_documents ADD COLUMN filename TEXT")
    op.execute("ALTER TABLE llm_calls ADD COLUMN trace_id TEXT")
    op.execute("CREATE INDEX llm_calls_trace_idx ON llm_calls (trace_id)")
    # The live_tenders view was created with SELECT *, which Postgres expands at creation
    # time; recreate it so it includes the new column.
    op.execute("""
        CREATE OR REPLACE VIEW live_tenders AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
    """)


def downgrade() -> None:
    op.execute("DROP VIEW live_tenders")
    op.execute("ALTER TABLE llm_calls DROP COLUMN trace_id")
    op.execute("ALTER TABLE tender_documents DROP COLUMN filename")
    op.execute("ALTER TABLE tenders DROP COLUMN summary")
    op.execute("ALTER TABLE tenders DROP COLUMN portal_fields")
    op.execute("""
        CREATE VIEW live_tenders AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
    """)
