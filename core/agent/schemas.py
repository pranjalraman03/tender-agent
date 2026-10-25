"""Pydantic models for every agent step's output (validated; one repair retry)."""

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "turnover",
    "experience",
    "registration",
    "certification",
    "location",
    "msme_status",
    "financial_capacity",
    "technical_capacity",
    "legal",
    "other",
]
Status = Literal["met", "not_met", "unclear", "exempt"]
Verdict = Literal["eligible", "possibly_eligible", "not_eligible", "needs_review"]


class Criterion(BaseModel):
    id: str = Field(description="Short id, e.g. 'C1'")
    description: str = Field(description="The requirement in one sentence, with numbers")
    category: Category
    clause_ids: list[int] = Field(description="Clauses that state this requirement")


class Plan(BaseModel):
    criteria: list[Criterion]


class Finding(BaseModel):
    criterion_id: str
    criterion: str
    status: Status
    clause_ids: list[int]
    note: str = Field(description="Why, in one or two sentences, citing the numbers compared")


class CheckResult(BaseModel):
    findings: list[Finding]


class Verification(BaseModel):
    supported: bool
    reason: str


class Report(BaseModel):
    verdict: Verdict
    findings: list[Finding]
    needs_review: bool
    review_reasons: list[str]
