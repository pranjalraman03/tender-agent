"""initial schema: all tables, live_tenders view, indexes, RLS

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

from core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIM = get_settings().embedding_dim

TENANT_TABLES = ["company_profiles", "matches", "eligibility_reports", "users"]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- Reference data -------------------------------------------------------
    op.execute("""
        CREATE TABLE industries (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE nic_industry_map (
            nic_prefix    TEXT NOT NULL,
            industry_slug TEXT NOT NULL REFERENCES industries(slug),
            PRIMARY KEY (nic_prefix, industry_slug)
        )
    """)

    # --- Public tender data ---------------------------------------------------
    op.execute("""
        CREATE TABLE portals (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            base_url   TEXT NOT NULL,
            crawl_cfg  JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"""
        CREATE TABLE tenders (
            id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            portal_id        BIGINT NOT NULL REFERENCES portals(id),
            tender_ref       TEXT NOT NULL,
            title            TEXT NOT NULL,
            org_name         TEXT,
            industries       TEXT[] NOT NULL DEFAULT '{{}}',
            work_state       TEXT,
            is_central       BOOLEAN NOT NULL DEFAULT false,
            value_inr        NUMERIC(18, 2),
            emd_inr          NUMERIC(18, 2),
            published_at     TIMESTAMPTZ,
            closes_at        TIMESTAMPTZ,
            pipeline_status  TEXT NOT NULL DEFAULT 'discovered'
                CHECK (pipeline_status IN ('discovered', 'downloaded', 'parsed', 'indexed', 'failed')),
            lifecycle_status TEXT NOT NULL DEFAULT 'open'
                CHECK (lifecycle_status IN ('open', 'extended', 'closed', 'cancelled', 'awarded')),
            last_checked_at  TIMESTAMPTZ,
            next_check_at    TIMESTAMPTZ,
            scope_embedding  vector({DIM}),
            source_url       TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (portal_id, tender_ref)
        )
    """)
    op.execute(
        "CREATE INDEX tenders_live_idx ON tenders (closes_at) "
        "WHERE lifecycle_status IN ('open', 'extended') AND pipeline_status = 'indexed'"
    )
    op.execute("CREATE INDEX tenders_industries_idx ON tenders USING gin (industries)")
    op.execute("CREATE INDEX tenders_next_check_idx ON tenders (next_check_at)")
    op.execute(
        "CREATE INDEX tenders_scope_embedding_idx ON tenders "
        "USING hnsw (scope_embedding vector_cosine_ops)"
    )

    op.execute("""
        CREATE TABLE tender_documents (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tender_id   BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            storage_key TEXT NOT NULL,
            sha256      TEXT NOT NULL UNIQUE,
            page_count  INTEGER,
            is_scanned  BOOLEAN NOT NULL DEFAULT false,
            parsed_at   TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX tender_documents_tender_idx ON tender_documents (tender_id)")

    op.execute(f"""
        CREATE TABLE clauses (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            document_id BIGINT NOT NULL REFERENCES tender_documents(id) ON DELETE CASCADE,
            tender_id   BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            clause_no   TEXT,
            section     TEXT,
            page_start  INTEGER NOT NULL,
            page_end    INTEGER NOT NULL,
            text        TEXT NOT NULL,
            embedding   vector({DIM}),
            tsv         tsvector GENERATED ALWAYS AS
                (to_tsvector('english', coalesce(section, '') || ' ' || text)) STORED,
            CHECK (page_end >= page_start)
        )
    """)
    op.execute("CREATE INDEX clauses_tender_idx ON clauses (tender_id)")
    op.execute(
        "CREATE INDEX clauses_embedding_idx ON clauses USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX clauses_tsv_idx ON clauses USING gin (tsv)")

    op.execute("""
        CREATE TABLE tender_events (
            id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tender_id   BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            kind        TEXT NOT NULL CHECK (kind IN
                ('published', 'corrigendum', 'extended', 'cancelled', 'awarded', 'closed')),
            old_value   JSONB,
            new_value   JSONB,
            document_id BIGINT REFERENCES tender_documents(id),
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX tender_events_tender_idx ON tender_events (tender_id, detected_at)")

    # The visibility rule. Every user-facing query reads from this view.
    op.execute("""
        CREATE VIEW live_tenders AS
          SELECT * FROM tenders
          WHERE lifecycle_status IN ('open', 'extended')
            AND pipeline_status = 'indexed'
            AND closes_at > now()
    """)

    # --- Tenant data ------------------------------------------------------------
    op.execute("""
        CREATE TABLE orgs (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE users (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id     UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            email      TEXT NOT NULL UNIQUE,
            role       TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member', 'admin')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX users_org_idx ON users (org_id)")

    op.execute(f"""
        CREATE TABLE company_profiles (
            id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            org_id              UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            version             INTEGER NOT NULL,
            website_url         TEXT,
            description         TEXT,
            industries          TEXT[] NOT NULL DEFAULT '{{}}',
            nic_codes           TEXT[] NOT NULL DEFAULT '{{}}',
            msme_category       TEXT CHECK (msme_category IN ('micro', 'small', 'medium')),
            states              TEXT[] NOT NULL DEFAULT '{{}}',
            annual_turnover_inr NUMERIC(18, 2),
            years_in_business   INTEGER,
            is_msme             BOOLEAN,
            certifications      TEXT[] NOT NULL DEFAULT '{{}}',
            past_projects       JSONB NOT NULL DEFAULT '[]',
            field_sources       JSONB NOT NULL DEFAULT '{{}}',
            confirmed_at        TIMESTAMPTZ,
            profile_embedding   vector({DIM}),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_id, version)
        )
    """)
    op.execute(
        "CREATE INDEX company_profiles_embedding_idx ON company_profiles "
        "USING hnsw (profile_embedding vector_cosine_ops)"
    )

    op.execute("""
        CREATE TABLE matches (
            org_id        UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            tender_id     BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            score         DOUBLE PRECISION,
            stage         TEXT NOT NULL CHECK (stage IN ('prefiltered', 'agent_checked')),
            fit           TEXT CHECK (fit IN ('good', 'possible', 'not_eligible')),
            user_state    TEXT CHECK (user_state IN ('saved', 'applying', 'dismissed')),
            needs_recheck BOOLEAN NOT NULL DEFAULT false,
            notified_at   TIMESTAMPTZ,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, tender_id)
        )
    """)
    op.execute("CREATE INDEX matches_tender_idx ON matches (tender_id)")

    op.execute("""
        CREATE TABLE eligibility_reports (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            tender_id       BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            profile_version INTEGER NOT NULL,
            verdict         TEXT NOT NULL
                CHECK (verdict IN ('eligible', 'possibly_eligible', 'not_eligible', 'needs_review')),
            findings        JSONB NOT NULL DEFAULT '[]',
            model           TEXT NOT NULL,
            trace_id        TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (org_id, tender_id, profile_version)
        )
    """)

    op.execute("""
        CREATE TABLE chat_messages (
            id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id       UUID NOT NULL,
            org_id           UUID REFERENCES orgs(id) ON DELETE CASCADE,
            tender_id        BIGINT NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
            role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content          TEXT NOT NULL,
            cited_clause_ids BIGINT[] NOT NULL DEFAULT '{}',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, created_at)")

    # --- Row-level security -------------------------------------------------------
    # FORCE makes RLS apply to the table owner too (the app connects as the owner).
    # Access is allowed when the transaction's app.org_id matches the row, or when
    # the transaction runs with app.role = 'system' (worker, scheduler, admin, evals).
    system = "current_setting('app.role', true) = 'system'"
    current_org = "org_id = nullif(current_setting('app.org_id', true), '')::uuid"
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_isolation ON {table}
              USING ({current_org} OR {system})
              WITH CHECK ({current_org} OR {system})
        """)
    # orgs: keyed by id rather than org_id.
    op.execute("ALTER TABLE orgs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE orgs FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY orgs_isolation ON orgs
          USING (id = nullif(current_setting('app.org_id', true), '')::uuid OR {system})
          WITH CHECK (id = nullif(current_setting('app.org_id', true), '')::uuid OR {system})
    """)
    # chat_messages: anonymous sessions (org_id IS NULL) are scoped by app.chat_session_id.
    op.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY")
    anon = (
        "org_id IS NULL AND session_id = "
        "nullif(current_setting('app.chat_session_id', true), '')::uuid"
    )
    op.execute(f"""
        CREATE POLICY chat_messages_isolation ON chat_messages
          USING ({current_org} OR ({anon}) OR {system})
          WITH CHECK ({current_org} OR ({anon}) OR {system})
    """)

    # --- Operations -------------------------------------------------------------------
    op.execute("""
        CREATE TABLE jobs (
            id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            kind            TEXT NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL UNIQUE,
            status          TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'done', 'dead', 'cancelled')),
            attempts        INTEGER NOT NULL DEFAULT 0,
            max_attempts    INTEGER NOT NULL DEFAULT 5,
            run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
            locked_at       TIMESTAMPTZ,
            last_error      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX jobs_status_run_after_idx ON jobs (status, run_after)")
    op.execute(
        "CREATE INDEX jobs_tender_idx ON jobs ((payload->>'tender_id')) WHERE status = 'queued'"
    )

    op.execute("""
        CREATE TABLE llm_calls (
            id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            purpose       TEXT NOT NULL,
            model         TEXT NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd      NUMERIC(12, 6) NOT NULL,
            latency_ms    INTEGER NOT NULL,
            org_id        UUID,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX llm_calls_created_idx ON llm_calls (created_at)")

    op.execute("""
        CREATE TABLE eval_cases (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name       TEXT NOT NULL UNIQUE,
            data       JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE eval_runs (
            id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            git_sha    TEXT,
            branch     TEXT,
            metrics    JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    for table in [
        "eval_runs",
        "eval_cases",
        "llm_calls",
        "jobs",
        "chat_messages",
        "eligibility_reports",
        "matches",
        "company_profiles",
        "users",
        "orgs",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP VIEW IF EXISTS live_tenders")
    for table in [
        "tender_events",
        "clauses",
        "tender_documents",
        "tenders",
        "portals",
        "nic_industry_map",
        "industries",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
