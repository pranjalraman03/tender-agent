from decimal import Decimal

import pytest

from core.agent.numeric import AmountParseError, compare, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rs. 1.5 crore", Decimal("15000000")),
        ("27,69,088/-", Decimal("2769088")),
        ("50 lakh", Decimal("5000000")),
        ("₹ 8.30 Lakhs", Decimal("830000")),
        ("INR 2,00,000", Decimal("200000")),
        ("7 years", Decimal("7")),
        (1250000, Decimal("1250000")),
    ],
)
def test_parse_amount(text: str | int, expected: Decimal) -> None:
    assert parse_amount(text) == expected


def test_compare() -> None:
    assert compare("50 lakh", "Rs 62,00,000", ">=")["satisfied"] is True
    assert compare("1 crore", "62 lakh", ">=")["satisfied"] is False
    assert compare("1 crore", "62 lakh", ">=")["difference"] == "-3800000"


def test_parse_amount_rejects_text() -> None:
    with pytest.raises(AmountParseError):
        parse_amount("not stated")
