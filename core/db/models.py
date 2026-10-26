"""SQLAlchemy models. The Alembic migrations are the source of truth for DDL
(views, RLS policies, generated columns, indexes); these models mirror the tables."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


def _now() -> Any:
    return mapped_column(server_default=func.now())


# --- Reference data ---------------------------------------------------------


class Industry(Base):
    __tablename__ = "industries"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class NicIndustryMap(Base):
    __tablename__ = "nic_industry_map"

    nic_prefix: Mapped[str] = mapped_column(Text, primary_key=True)
    industry_slug: Mapped[str] = mapped_column(ForeignKey("industries.slug"), primary_key=True)


# --- Public tender data -----------------------------------------------------


class Portal(Base):
    __tablename__ = "portals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    base_url: Mapped[str] = mapped_column(Text)
    crawl_cfg: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = _now()


class Tender(Base):
    __tablename__ = "tenders"
    __table_args__ = (UniqueConstraint("portal_id", "tender_ref"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portal_id: Mapped[int] = mapped_column(ForeignKey("portals.id"))
    tender_ref: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    org_name: Mapped[str | None] = mapped_column(Text)
    industries: Mapped[list[str]] = mapped_column(server_default="{}")
    work_state: Mapped[str | None] = mapped_column(Text)
    is_central: Mapped[bool] = mapped_column(Boolean, server_default="false")
    value_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    emd_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    published_at: Mapped[datetime | None]
    closes_at: Mapped[datetime | None]
    pipeline_status: Mapped[str] = mapped_column(Text, server_default="discovered")
    lifecycle_status: Mapped[str] = mapped_column(Text, server_default="open")
    last_checked_at: Mapped[datetime | None]
    next_check_at: Mapped[datetime | None]
    scope_embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    source_url: Mapped[str | None] = mapped_column(Text)
    portal_fields: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class TenderDocument(Base):
    __tablename__ = "tender_documents"
    __table_args__ = (
        UniqueConstraint("tender_id", "sha256", name="tender_documents_tender_sha_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="crawler")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    sha256: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    is_scanned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    parsed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _now()


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("tender_documents.id", ondelete="CASCADE"))
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    clause_no: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(section, '') || ' ' || text)", persisted=True),
    )


class TenderEvent(Base):
    __tablename__ = "tender_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    old_value: Mapped[dict[str, Any] | None]
    new_value: Mapped[dict[str, Any] | None]
    document_id: Mapped[int | None] = mapped_column(ForeignKey("tender_documents.id"))
    detected_at: Mapped[datetime] = _now()


# --- Tenant data (org_id + RLS) --------------------------------------------


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default="member")
    created_at: Mapped[datetime] = _now()


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    __table_args__ = (UniqueConstraint("org_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    website_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    industries: Mapped[list[str]] = mapped_column(server_default="{}")
    nic_codes: Mapped[list[str]] = mapped_column(server_default="{}")
    msme_category: Mapped[str | None] = mapped_column(Text)
    states: Mapped[list[str]] = mapped_column(server_default="{}")
    annual_turnover_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    years_in_business: Mapped[int | None] = mapped_column(Integer)
    is_msme: Mapped[bool | None] = mapped_column(Boolean)
    certifications: Mapped[list[str]] = mapped_column(server_default="{}")
    past_projects: Mapped[dict[str, Any]] = mapped_column(server_default="[]")
    field_sources: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    confirmed_at: Mapped[datetime | None]
    profile_embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    turnover_by_year: Mapped[dict[str, Any]] = mapped_column(server_default="[]")
    incorporated_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()


class CompanyDocument(Base):
    __tablename__ = "company_documents"
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any] | None]
    uploaded_at: Mapped[datetime] = _now()


class Match(Base):
    __tablename__ = "matches"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orgs.id", ondelete="CASCADE"), primary_key=True
    )
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float | None]
    stage: Mapped[str] = mapped_column(Text)
    fit: Mapped[str | None] = mapped_column(Text)
    user_state: Mapped[str | None] = mapped_column(Text)
    needs_recheck: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notified_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = _now()


class EligibilityReport(Base):
    __tablename__ = "eligibility_reports"
    __table_args__ = (UniqueConstraint("org_id", "tender_id", "profile_version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    profile_version: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(Text)
    findings: Mapped[dict[str, Any]] = mapped_column(server_default="[]")
    model: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"))
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    cited_clause_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), server_default="{}")
    created_at: Mapped[datetime] = _now()


# --- Operations -------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    run_after: Mapped[datetime] = _now()
    locked_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class RateLimit(Base):
    __tablename__ = "rate_limits"

    bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default="0")


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    trace_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    data: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _now()


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    git_sha: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = _now()
