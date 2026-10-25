"""Deterministic number handling for eligibility checks. The model never does arithmetic:
it passes the requirement and the company's value (as written) and code compares them."""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

Rule = Literal[">=", ">", "<=", "<", "=="]

_MULTIPLIERS = {
    "crore": Decimal(10_000_000),
    "crores": Decimal(10_000_000),
    "cr": Decimal(10_000_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "lac": Decimal(100_000),
    "lacs": Decimal(100_000),
    "l": Decimal(100_000),
    "thousand": Decimal(1000),
    "k": Decimal(1000),
    "million": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
}
_NUMBER = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*([a-zA-Z]+)?")


class AmountParseError(ValueError):
    pass


def parse_amount(value: str | float | int) -> Decimal:
    """'Rs. 1.5 crore' -> 15000000; '27,69,088/-' -> 2769088; '50 lakh' -> 5000000."""
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    cleaned = value.lower().replace("rs.", " ").replace("rs", " ").replace("inr", " ")
    cleaned = cleaned.replace("₹", " ").replace("/-", " ")
    match = _NUMBER.search(cleaned)
    if not match:
        raise AmountParseError(f"no number in {value!r}")
    try:
        number = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation as exc:
        raise AmountParseError(f"bad number in {value!r}") from exc
    unit = (match.group(2) or "").lower()
    return number * _MULTIPLIERS.get(unit, Decimal(1))


def compare(requirement: str | float, actual: str | float, rule: Rule) -> dict[str, object]:
    req, act = parse_amount(requirement), parse_amount(actual)
    result = {
        ">=": act >= req,
        ">": act > req,
        "<=": act <= req,
        "<": act < req,
        "==": act == req,
    }[rule]
    return {
        "requirement": str(req),
        "actual": str(act),
        "rule": f"actual {rule} requirement",
        "satisfied": result,
        "difference": str(act - req),
    }
