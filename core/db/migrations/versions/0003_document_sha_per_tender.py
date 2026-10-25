"""tender_documents: sha256 unique per tender, not globally

The same PDF (e.g. standard General Conditions of Contract) is often attached to many
tenders. With a global UNIQUE(sha256) the second tender silently got no document.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tender_documents DROP CONSTRAINT tender_documents_sha256_key")
    op.execute(
        "ALTER TABLE tender_documents ADD CONSTRAINT tender_documents_tender_sha_key "
        "UNIQUE (tender_id, sha256)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tender_documents DROP CONSTRAINT tender_documents_tender_sha_key")
    op.execute(
        "ALTER TABLE tender_documents ADD CONSTRAINT tender_documents_sha256_key UNIQUE (sha256)"
    )
