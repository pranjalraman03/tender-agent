"""Request / response models for the API. The frontend's TypeScript types are generated
from the OpenAPI schema these produce."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class IndustryOut(BaseModel):
    slug: str
    name: str


class Meta(BaseModel):
    industries: list[IndustryOut]
    states: list[str]
    llm_configured: bool


class TenderCard(BaseModel):
    id: int
    title: str
    org_name: str | None
    work_state: str | None
    is_central: bool
    industries: list[str]
    value_inr: Decimal | None
    emd_inr: Decimal | None
    closes_at: datetime | None
    published_at: datetime | None
    summary: str | None


class TenderPage(BaseModel):
    items: list[TenderCard]
    total: int
    page: int
    page_size: int


class DocumentOut(BaseModel):
    id: int
    filename: str | None
    page_count: int | None
    is_scanned: bool
    parsed_at: datetime | None


class TenderEventOut(BaseModel):
    kind: str
    detected_at: datetime
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None


class TenderDetail(TenderCard):
    tender_ref: str
    portal: str
    source_url: str | None
    reference_no: str | None
    documents: list[DocumentOut]
    events: list[TenderEventOut]


class ClauseOut(BaseModel):
    id: int
    document_id: int
    clause_no: str | None
    section: str | None
    page_start: int
    page_end: int
    text: str


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    question: str = Field(min_length=2, max_length=1000)


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    cited_clause_ids: list[int]
    created_at: datetime


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str


class Me(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    org: OrgOut
    has_confirmed_profile: bool


class PastProject(BaseModel):
    title: str
    client: str | None = None
    value_inr: float | None = None
    year: int | None = None


class ProfileOut(BaseModel):
    id: int
    version: int
    confirmed_at: datetime | None
    website_url: str | None
    description: str | None
    industries: list[str]
    nic_codes: list[str]
    msme_category: str | None
    states: list[str]
    annual_turnover_inr: Decimal | None
    years_in_business: int | None
    is_msme: bool | None
    certifications: list[str]
    past_projects: list[dict[str, Any]]
    field_sources: dict[str, Any]
    extraction_pending: bool = False


class ProfileState(BaseModel):
    draft: ProfileOut | None
    confirmed: ProfileOut | None


class WebsiteRequest(BaseModel):
    url: HttpUrl


class ProfileUpdate(BaseModel):
    company_name: str | None = Field(None, max_length=200)
    website_url: str | None = None
    description: str | None = Field(None, max_length=4000)
    industries: list[str] | None = None
    nic_codes: list[str] | None = None
    msme_category: Literal["micro", "small", "medium"] | None = None
    states: list[str] | None = None
    annual_turnover_inr: float | None = Field(None, ge=0)
    years_in_business: int | None = Field(None, ge=0, le=200)
    is_msme: bool | None = None
    certifications: list[str] | None = None
    past_projects: list[PastProject] | None = None


class UdyamOut(BaseModel):
    udyam_number: str
    msme_category: str | None
    nic_codes: list[str]
    states: list[str]


class MatchOut(BaseModel):
    tender: TenderCard
    score: float | None
    stage: str
    fit: str | None
    user_state: str | None
    needs_recheck: bool
    verdict: str | None
    updated_at: datetime


class MatchUpdate(BaseModel):
    user_state: Literal["saved", "applying", "dismissed"] | None


class FindingOut(BaseModel):
    criterion_id: str
    criterion: str
    status: str
    clause_ids: list[int]
    note: str


class ReportOut(BaseModel):
    tender_id: int
    profile_version: int
    verdict: str
    findings: list[FindingOut]
    clauses: list[ClauseOut]
    model: str
    created_at: datetime
    stale: bool  # report is for an older profile version


class UploadResult(BaseModel):
    new_documents: int
    duplicates: int
    skipped_files: list[str]


class NeededDocsItem(BaseModel):
    tender_id: int
    title: str
    org_name: str | None
    reference_no: str | None
    portal_tender_id: str
    closes_at: datetime | None
    reason: Literal["no_documents", "corrigendum"]
    portal_url: str


class JobStat(BaseModel):
    kind: str
    status: str
    count: int


class DeadJob(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int
    last_error: str | None
    updated_at: datetime


class AdminOverview(BaseModel):
    jobs: list[JobStat]
    dead: list[DeadJob]
    tenders_by_status: list[dict[str, Any]]
    llm_cost_7d: list[dict[str, Any]]
    eval_runs: list[dict[str, Any]]
    llm_configured: bool
