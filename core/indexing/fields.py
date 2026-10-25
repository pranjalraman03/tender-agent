"""Tender field extraction: one fast-model call with a JSON schema per tender."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.llm.claude import (
    UNTRUSTED_NOTE,
    CallContext,
    Claude,
    Usage,
    strict_schema,
    wrap_untrusted,
)
from core.reference.states import STATES

PROMPT_VERSION = "extract_fields_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()

PORTAL_KEYS = [
    "Work Description",
    "Product Category",
    "Sub category",
    "Tender Category",
    "Location",
    "Pincode",
    "Tender Value in ₹",
    "EMD Amount in ₹",
    "Organisation Chain",
]
KEYWORDS = (
    "eligib",
    "qualif",
    "turnover",
    "experience",
    "scope",
    "work",
    "supply",
    "location",
    "msme",
    "mse",
    "startup",
    "emd",
    "earnest",
)
MAX_CONTEXT_CHARS = 15000


class TenderFields(BaseModel):
    industries: list[str] = Field(max_length=3)
    work_state: str | None
    is_central: bool
    value_inr: float | None
    emd_inr: float | None
    summary: str


def _schema(allowed_industries: list[str]) -> dict[str, Any]:
    schema = strict_schema(TenderFields)
    schema["properties"]["industries"]["items"] = {"type": "string", "enum": allowed_industries}
    schema["properties"]["work_state"] = {
        "anyOf": [{"type": "string", "enum": STATES}, {"type": "null"}]
    }
    return schema


def build_context(tender: Any, clauses: list[Any]) -> str:
    portal = "\n".join(
        f"{k}: {tender.portal_fields[k]}" for k in PORTAL_KEYS if tender.portal_fields.get(k)
    )
    picked: list[str] = []
    size = 0
    # The opening clauses (the notice itself), then clauses mentioning the key topics.
    ordered = clauses[:8] + [c for c in clauses[8:] if any(k in c.text.lower() for k in KEYWORDS)]
    for c in ordered:
        piece = f"[clause {c.clause_no or '-'}, p.{c.page_start}] {c.text}"
        if size + len(piece) > MAX_CONTEXT_CHARS:
            break
        picked.append(piece)
        size += len(piece)
    return f"Title: {tender.title}\nBuyer: {tender.org_name}\n{portal}\n\n" + "\n\n".join(picked)


async def extract_fields(
    claude: Claude,
    tender: Any,
    clauses: list[Any],
    allowed_industries: list[str],
    ctx: CallContext,
) -> tuple[TenderFields, Usage]:
    user = f"Allowed industry slugs: {', '.join(allowed_industries)}\n\n" + wrap_untrusted(
        "tender", build_context(tender, clauses)
    )
    schema = _schema(allowed_industries)
    response, usage = await claude.create(
        ctx,
        tier="fast",
        system=PROMPT + "\n\n" + UNTRUSTED_NOTE,
        messages=[{"role": "user", "content": user}],
        max_tokens=4000,
        effort="low",
        output_schema=schema,
    )
    raw = "".join(b.text for b in response.content if b.type == "text")
    fields = TenderFields.model_validate_json(raw)
    # Defence in depth: never trust labels outside the reference list.
    fields.industries = [i for i in fields.industries if i in allowed_industries]
    if fields.work_state not in STATES:
        fields.work_state = None
    return fields, usage


def to_decimal(v: float | None) -> Decimal | None:
    return None if v is None or v < 0 else Decimal(str(round(v, 2)))
