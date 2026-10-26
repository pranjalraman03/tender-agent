"""CA turnover certificates -> per-financial-year turnover in the profile draft.

The fast model reads the certificate text and returns one row per financial year with an
exact quote. Code then checks every row: the financial year must parse, the amount must be
positive, and the quote must actually appear in the certificate text. Rows that fail are
dropped, never guessed. The user reviews the figures before confirming the profile.
"""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.agent.turnover import TurnoverRuleError, fy_label, parse_fy
from core.llm.claude import (
    UNTRUSTED_NOTE,
    CallContext,
    Claude,
    Usage,
    strict_schema,
    wrap_untrusted,
)

PROMPT_VERSION = "ca_turnover_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
MAX_TEXT_CHARS = 20000


class TurnoverRow(BaseModel):
    financial_year: str = Field(description="e.g. 2024-25")
    turnover_inr: float = Field(description="Turnover in rupees as a plain number")
    quote: str = Field(description="Exact text from the certificate stating this figure")


class CertificateExtraction(BaseModel):
    is_turnover_certificate: bool
    issued_by: str | None
    certificate_date: str | None
    rows: list[TurnoverRow]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_rows(
    extraction: CertificateExtraction, document_text: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep rows with a valid FY, positive amount and a quote found in the document.
    Returns (rows, rejection reasons). Later rows for the same FY are ignored."""
    haystack = _norm(document_text)
    kept: dict[int, dict[str, Any]] = {}
    rejected: list[str] = []
    for row in extraction.rows:
        try:
            start = parse_fy(row.financial_year)
        except TurnoverRuleError:
            rejected.append(f"unrecognised financial year {row.financial_year!r}")
            continue
        if row.turnover_inr <= 0:
            rejected.append(f"{fy_label(start)}: non-positive amount")
            continue
        if not row.quote.strip() or _norm(row.quote) not in haystack:
            rejected.append(f"{fy_label(start)}: quote not found in the certificate")
            continue
        if start in kept:
            continue
        kept[start] = {
            "financial_year": fy_label(start),
            "turnover_inr": float(Decimal(str(row.turnover_inr))),
            "quote": row.quote.strip()[:300],
        }
    rows = [kept[y] for y in sorted(kept, reverse=True)]
    return rows, rejected


async def extract_certificate(
    claude: Claude, document_text: str, ctx: CallContext
) -> tuple[CertificateExtraction, Usage]:
    schema = strict_schema(CertificateExtraction)
    response, usage = await claude.create(
        ctx,
        tier="fast",
        system=PROMPT + "\n\n" + UNTRUSTED_NOTE,
        messages=[
            {
                "role": "user",
                "content": wrap_untrusted("ca_certificate", document_text[:MAX_TEXT_CHARS]),
            }
        ],
        max_tokens=4000,
        effort="low",
        output_schema=schema,
    )
    raw = "".join(b.text for b in response.content if b.type == "text")
    return CertificateExtraction.model_validate_json(raw), usage


def merge_turnover(
    existing: list[dict[str, Any]] | None, new_rows: list[dict[str, Any]], source: dict[str, Any]
) -> list[dict[str, Any]]:
    """Newer certificate figures replace older ones for the same FY; other years are kept."""
    by_fy: dict[str, dict[str, Any]] = {}
    for row in existing or []:
        try:
            by_fy[fy_label(parse_fy(str(row["financial_year"])))] = row
        except (KeyError, TurnoverRuleError):
            continue
    for row in new_rows:
        by_fy[row["financial_year"]] = {
            "financial_year": row["financial_year"],
            "turnover_inr": row["turnover_inr"],
            "source": {**source, "quote": row["quote"]},
        }
    return [by_fy[k] for k in sorted(by_fy, key=parse_fy, reverse=True)]


def latest_turnover(rows: list[dict[str, Any]] | None) -> float | None:
    """Most recent year's figure, kept in annual_turnover_inr for display and ranking."""
    if not rows:
        return None
    newest = max(rows, key=lambda r: parse_fy(str(r["financial_year"])))
    return float(newest["turnover_inr"])


def dumps(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, default=str)
