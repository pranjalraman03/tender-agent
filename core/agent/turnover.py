"""Turnover criteria, computed in code from per-financial-year figures.

Tenders phrase turnover rules many ways ("average of the last 3 financial years", "in each
of the last 5 years", "in any one of the last 3 years", "average of the best 3 of the last 5").
The model only extracts the rule; this module decides which financial years apply and does
the arithmetic, so no tender-specific code is ever needed.

Indian financial years run 1 April - 31 March and are labelled "2024-25".

Outcomes:
- met / not_met: every year the rule needs is available and the comparison is decided.
- missing_data: the company existed in a year the rule needs, but no turnover figure for it
  is on file -> the user should upload a CA turnover certificate covering that year.
- company_too_young: the rule needs years before the company was incorporated.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from core.agent.numeric import parse_amount

Aggregation = Literal["average", "each_year", "any_one_year", "total", "best_k_of_n"]
AGGREGATIONS: tuple[Aggregation, ...] = (
    "average",
    "each_year",
    "any_one_year",
    "total",
    "best_k_of_n",
)
_FY = re.compile(r"(?:FY\s*)?(\d{4})\s*[-–/]\s*(\d{4}|\d{2})(?!\d)", re.I)


class TurnoverRuleError(ValueError):
    pass


def fy_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def parse_fy(label: str) -> int:
    """'2024-25' / '2024-2025' / 'FY 2024-25' -> 2024 (the year the FY starts)."""
    m = _FY.search(label)
    if not m:
        raise TurnoverRuleError(f"not a financial year: {label!r}")
    start, end = int(m.group(1)), m.group(2)
    end_year = int(end) if len(end) == 4 else (start // 100) * 100 + int(end)
    if end_year != start + 1:
        raise TurnoverRuleError(f"not a single financial year: {label!r}")
    return start


def fy_containing(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_end(start_year: int) -> date:
    return date(start_year + 1, 3, 31)


def last_year_of_period(period_end: str | None, as_of: date) -> int:
    """Start year of the last financial year the rule covers.

    period_end may be a date ("2026-03-31"), a financial year ("2025-26"), or None, which
    means the last financial year completed before `as_of` (normally the bid deadline).
    """
    if period_end:
        try:
            return fy_containing(date.fromisoformat(period_end.strip()))
        except ValueError:
            return parse_fy(period_end)
    current = fy_containing(as_of)
    return current if as_of >= fy_end(current) else current - 1


@dataclass(frozen=True)
class TurnoverRule:
    aggregation: Aggregation
    years: int
    amount: str
    best_k: int | None = None
    period_end: str | None = None

    def validate(self) -> None:
        if self.aggregation not in AGGREGATIONS:
            raise TurnoverRuleError(f"unknown aggregation {self.aggregation!r}")
        if not 1 <= self.years <= 20:
            raise TurnoverRuleError("years must be between 1 and 20")
        if self.aggregation == "best_k_of_n" and not (
            self.best_k and 1 <= self.best_k <= self.years
        ):
            raise TurnoverRuleError("best_k_of_n needs 1 <= best_k <= years")


def figures_from_profile(turnover_by_year: list[dict[str, Any]] | None) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for row in turnover_by_year or []:
        try:
            out[parse_fy(str(row["financial_year"]))] = Decimal(str(row["turnover_inr"]))
        except (KeyError, TurnoverRuleError, ArithmeticError, ValueError):
            continue
    return out


def _inr(v: Decimal) -> str:
    if v >= 10_000_000:
        return f"Rs {v / 10_000_000:.2f} crore"
    if v >= 100_000:
        return f"Rs {v / 100_000:.2f} lakh"
    return f"Rs {v:,.0f}"


def evaluate(
    rule: TurnoverRule, figures: dict[int, Decimal], incorporated_on: date | None, as_of: date
) -> dict[str, Any]:
    rule.validate()
    required_amount = parse_amount(rule.amount)
    last = last_year_of_period(rule.period_end, as_of)
    window = [last - i for i in range(rule.years)]  # newest first
    # A year "existed" for the company if it was incorporated on or before that FY's end.
    before_incorporation = [
        y for y in window if incorporated_on is not None and fy_end(y) < incorporated_on
    ]
    existing = [y for y in window if y not in before_incorporation]
    available = {y: figures[y] for y in existing if y in figures}
    missing = [y for y in existing if y not in figures]

    def result(outcome: str, value: Decimal | None, explanation: str) -> dict[str, Any]:
        status = {
            "met": "met",
            "not_met": "not_met",
            "company_too_young": "not_met",
            "missing_data": "unclear",
        }[outcome]
        return {
            "outcome": outcome,
            "status": status,
            "rule": f"{rule.aggregation} over {rule.years} FY(s)"
            + (f", best {rule.best_k}" if rule.best_k else "")
            + f", required {_inr(required_amount)}",
            "financial_years_required": [fy_label(y) for y in window],
            "figures_used": {fy_label(y): str(v) for y, v in sorted(available.items())},
            "computed_value": str(value) if value is not None else None,
            "required_amount": str(required_amount),
            "missing_years": [fy_label(y) for y in missing],
            "years_before_incorporation": [fy_label(y) for y in before_incorporation],
            "explanation": explanation,
        }

    agg = rule.aggregation
    needs_full_history = agg in ("average", "each_year", "total")
    if needs_full_history and before_incorporation:
        return result(
            "company_too_young",
            None,
            f"The rule covers FY {fy_label(window[-1])} to {fy_label(window[0])}, but the "
            f"company was incorporated on {incorporated_on}, so it has no turnover for "
            f"{', '.join(fy_label(y) for y in before_incorporation)}.",
        )
    if agg == "best_k_of_n" and len(existing) < (rule.best_k or 0):
        return result(
            "company_too_young",
            None,
            f"The rule needs the best {rule.best_k} of {rule.years} years, but the company "
            f"existed in only {len(existing)} of them.",
        )

    missing_text = ", ".join(fy_label(y) for y in missing)
    if agg in ("average", "each_year", "total"):
        if missing:
            return result(
                "missing_data",
                None,
                f"Turnover for FY {missing_text} is not on file; upload a CA turnover "
                f"certificate covering it.",
            )
        values = list(available.values())
        if agg == "average":
            value = sum(values, Decimal(0)) / len(values)
            label = f"average of FY {fy_label(window[-1])} to {fy_label(window[0])}"
        elif agg == "total":
            value = sum(values, Decimal(0))
            label = f"total of FY {fy_label(window[-1])} to {fy_label(window[0])}"
        else:
            value = min(values)
            label = "lowest year in the period"
        ok = value >= required_amount
        return result(
            "met" if ok else "not_met",
            value,
            f"{label.capitalize()} = {_inr(value)} "
            f"{'≥' if ok else '<'} required {_inr(required_amount)}.",
        )

    if agg == "any_one_year":
        best = max(available.values(), default=None)
        if best is not None and best >= required_amount:
            year = max(available, key=lambda y: available[y])
            return result(
                "met",
                best,
                f"FY {fy_label(year)} turnover {_inr(best)} ≥ required {_inr(required_amount)}.",
            )
        if missing:
            return result(
                "missing_data",
                best,
                f"No year on file reaches {_inr(required_amount)}; turnover for FY "
                f"{missing_text} is not on file.",
            )
        if not existing:
            return result(
                "company_too_young", None, "The company did not exist in any year of the period."
            )
        return result(
            "not_met",
            best,
            f"Highest year {_inr(best or Decimal(0))} < required {_inr(required_amount)}.",
        )

    # best_k_of_n
    k = rule.best_k or 1
    top = sorted(available.values(), reverse=True)[:k]
    best_avg: Decimal | None = sum(top, Decimal(0)) / len(top) if len(top) == k else None
    if best_avg is not None and best_avg >= required_amount:
        return result(
            "met",
            best_avg,
            f"Average of the best {k} years = {_inr(best_avg)} ≥ required {_inr(required_amount)}.",
        )
    if missing:
        return result(
            "missing_data",
            best_avg,
            f"Turnover for FY {missing_text} is not on file; with it the best {k} years "
            f"may reach {_inr(required_amount)}.",
        )
    return result(
        "not_met",
        best_avg,
        f"Average of the best {k} years = {_inr(best_avg or Decimal(0))} < "
        f"required {_inr(required_amount)}.",
    )
