"""Per-year turnover and incorporation date on profiles; company_documents for uploads

Turnover rules differ between tenders (average of 3 or 5 years, each year, any one year...),
so profiles keep raw per-financial-year figures and code computes whatever a tender asks for.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [{"financial_year": "2024-25", "turnover_inr": 3100000, "source": {...}}]
    op.execute(
        "ALTER TABLE company_profiles ADD COLUMN turnover_by_year JSONB NOT NULL DEFAULT '[]'"
    )
    op.execute("ALTER TABLE company_profiles ADD COLUMN incorporated_on DATE")

    op.execute("""
        CREATE TABLE company_documents (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            org_id      UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            kind        TEXT NOT NULL CHECK (kind IN ('ca_turnover_certificate', 'udyam')),
            storage_key TEXT NOT NULL,
            sha256      TEXT NOT NULL,
            filename    TEXT,
            extracted   JSONB,
            uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_id, sha256)
        )
    """)
    system = "current_setting('app.role', true) = 'system'"
    current_org = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
    op.execute("ALTER TABLE company_documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE company_documents FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY company_documents_isolation ON company_documents
          USING ({current_org} OR {system})
          WITH CHECK ({current_org} OR {system})
    """)


def downgrade() -> None:
    op.execute("DROP TABLE company_documents")
    op.execute("ALTER TABLE company_profiles DROP COLUMN incorporated_on")
    op.execute("ALTER TABLE company_profiles DROP COLUMN turnover_by_year")
