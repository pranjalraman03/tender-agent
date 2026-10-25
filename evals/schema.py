"""Golden case format. One JSON file per case in evals/golden/.

Gold citations are text snippets, not clause ids: ids change whenever a PDF is re-parsed,
snippets don't. A predicted clause "hits" a gold criterion if its text contains one of the
criterion's evidence snippets (whitespace- and case-insensitive).
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["met", "not_met", "unclear", "exempt"]
Verdict = Literal["eligible", "possibly_eligible", "not_eligible", "needs_review"]


class GoldCriterion(BaseModel):
    description: str
    status: Status
    evidence: list[str] = Field(min_length=1, description="Snippets from the stating clause(s)")
    query: str | None = Field(None, description="Retrieval query; defaults to description")


class GoldCase(BaseModel):
    name: str
    synthetic: bool = False  # True for format/smoke cases, excluded from headline metrics
    pdfs: list[str]  # paths relative to evals/golden/pdfs/
    tender: dict[str, Any]  # title, org_name, portal_fields, ...
    profile: dict[str, Any]  # company_profiles fields
    verdict: Verdict
    criteria: list[GoldCriterion]
    notes: str = ""


def normalise(s: str) -> str:
    return " ".join(s.lower().split())


def clause_hits(clause_text: str, criterion: GoldCriterion) -> bool:
    body = normalise(clause_text)
    return any(normalise(e) in body for e in criterion.evidence)
