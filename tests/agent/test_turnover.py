"""Turnover rules computed in code. Includes the owner's scenarios:
- tender needs 10 years, company is 5 years old         -> not met (too young)
- tender needs 5 years, certificate shows only 3        -> unclear, names missing years
- tender needs 3 years, certificate shows 3             -> decided (met / not met)
"""

from datetime import date
from decimal import Decimal

import pytest

from core.agent.turnover import (
    TurnoverRule,
    TurnoverRuleError,
    evaluate,
    figures_from_profile,
    fy_containing,
    fy_label,
    last_year_of_period,
    parse_fy,
)

BID_DATE = date(2026, 11, 25)  # last completed FY before this: 2025-26


def figs(**by_fy: float) -> dict[int, Decimal]:
    return {parse_fy(k.replace("_", "-")): Decimal(str(v)) for k, v in by_fy.items()}


THREE_YEARS = figs(**{"2025_26": 3_800_000, "2024_25": 3_100_000, "2023_24": 2_700_000})


def test_fy_helpers() -> None:
    assert fy_label(2024) == "2024-25" and fy_label(1999) == "1999-00"
    assert parse_fy("FY 2024-25") == parse_fy("2024-2025") == 2024
    assert fy_containing(date(2026, 3, 31)) == 2025 and fy_containing(date(2026, 4, 1)) == 2026
    assert last_year_of_period(None, BID_DATE) == 2025
    assert last_year_of_period(None, date(2026, 3, 31)) == 2025  # FY ends that day
    assert last_year_of_period("2025-03-31", BID_DATE) == 2024
    assert last_year_of_period("2023-24", BID_DATE) == 2023
    with pytest.raises(TurnoverRuleError):
        parse_fy("2024-27")


def test_three_years_required_three_on_file_is_decided() -> None:
    r = evaluate(TurnoverRule("average", 3, "14.55 lakh"), THREE_YEARS, date(2016, 5, 12), BID_DATE)
    assert r["outcome"] == "met" and r["status"] == "met"
    assert r["financial_years_required"] == ["2025-26", "2024-25", "2023-24"]
    assert Decimal(r["computed_value"]) == Decimal(3_200_000)
    r = evaluate(TurnoverRule("average", 3, "50 lakh"), THREE_YEARS, date(2016, 5, 12), BID_DATE)
    assert r["outcome"] == "not_met"


def test_five_years_required_three_on_file_names_missing_years() -> None:
    r = evaluate(TurnoverRule("average", 5, "14.55 lakh"), THREE_YEARS, date(2016, 5, 12), BID_DATE)
    assert r["outcome"] == "missing_data" and r["status"] == "unclear"
    assert r["missing_years"] == ["2022-23", "2021-22"]
    assert "2022-23" in r["explanation"] and "CA turnover certificate" in r["explanation"]


def test_ten_years_required_company_five_years_old_is_not_eligible() -> None:
    r = evaluate(TurnoverRule("average", 10, "10 lakh"), THREE_YEARS, date(2021, 6, 1), BID_DATE)
    assert r["outcome"] == "company_too_young" and r["status"] == "not_met"
    assert r["years_before_incorporation"][0] == "2020-21"
    assert "2016-17" in r["years_before_incorporation"]


def test_partial_first_year_counts_as_existing() -> None:
    # Incorporated in Sep 2023: FY 2023-24 existed (partly), so it's needed, not "too young".
    r = evaluate(TurnoverRule("average", 3, "10 lakh"), THREE_YEARS, date(2023, 9, 1), BID_DATE)
    assert r["outcome"] == "met"


def test_one_year_rule() -> None:
    r = evaluate(TurnoverRule("average", 1, "35 lakh"), THREE_YEARS, None, BID_DATE)
    assert r["outcome"] == "met" and r["financial_years_required"] == ["2025-26"]


def test_each_year_uses_the_lowest_year() -> None:
    r = evaluate(TurnoverRule("each_year", 3, "30 lakh"), THREE_YEARS, None, BID_DATE)
    assert r["outcome"] == "not_met" and Decimal(r["computed_value"]) == Decimal(2_700_000)


def test_any_one_year_can_pass_despite_missing_years() -> None:
    r = evaluate(TurnoverRule("any_one_year", 5, "35 lakh"), THREE_YEARS, None, BID_DATE)
    assert r["outcome"] == "met"
    r = evaluate(TurnoverRule("any_one_year", 5, "50 lakh"), THREE_YEARS, None, BID_DATE)
    assert r["outcome"] == "missing_data"  # a missing year might be higher


def test_best_k_of_n() -> None:
    r = evaluate(TurnoverRule("best_k_of_n", 5, "34 lakh", best_k=2), THREE_YEARS, None, BID_DATE)
    assert r["outcome"] == "met" and Decimal(r["computed_value"]) == Decimal(3_450_000)
    r = evaluate(
        TurnoverRule("best_k_of_n", 5, "35 lakh", best_k=3), THREE_YEARS, date(2024, 1, 1), BID_DATE
    )
    assert r["outcome"] == "not_met"  # all existing years on file, best 3 avg = 32 lakh


def test_explicit_period_end() -> None:
    r = evaluate(
        TurnoverRule("average", 2, "10 lakh", period_end="2025-03-31"), THREE_YEARS, None, BID_DATE
    )
    assert r["financial_years_required"] == ["2024-25", "2023-24"] and r["outcome"] == "met"


def test_figures_from_profile_ignores_bad_rows() -> None:
    rows = [
        {"financial_year": "2024-25", "turnover_inr": 100},
        {"financial_year": "garbage", "turnover_inr": 5},
        {"turnover_inr": 7},
    ]
    assert figures_from_profile(rows) == {2024: Decimal(100)}


def test_invalid_rules() -> None:
    with pytest.raises(TurnoverRuleError):
        evaluate(TurnoverRule("best_k_of_n", 3, "1 lakh"), {}, None, BID_DATE)
    with pytest.raises(TurnoverRuleError):
        evaluate(TurnoverRule("average", 0, "1 lakh"), {}, None, BID_DATE)


async def test_check_turnover_tool_uses_profile_and_bid_deadline(sessionmaker, portal_id) -> None:  # type: ignore[no-untyped-def]
    import uuid

    from sqlalchemy import text

    from core.agent.tools import AgentTools

    async with sessionmaker() as s, s.begin():
        tid = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, closes_at) VALUES "
                    "(:p, 'T', 't', '2026-11-25 17:00+05:30') RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
    profile = {
        "company_name": "x",
        "incorporated_on": date(2016, 5, 12),
        "turnover_by_year": [
            {"financial_year": "2025-26", "turnover_inr": 3800000},
            {"financial_year": "2024-25", "turnover_inr": 3100000},
            {"financial_year": "2023-24", "turnover_inr": 2700000},
        ],
    }
    async with sessionmaker() as s:
        tools = AgentTools(s, tid, uuid.uuid4(), profile)
        three = await tools.run(
            "check_turnover",
            {
                "aggregation": "average",
                "years": 3,
                "best_k": None,
                "amount": "Rs. 14.55 lakh",
                "period_end": None,
            },
        )
        five = await tools.run(
            "check_turnover",
            {
                "aggregation": "average",
                "years": 5,
                "best_k": None,
                "amount": "14.55 lakh",
                "period_end": None,
            },
        )
    assert three["outcome"] == "met" and three["financial_years_required"][0] == "2025-26"
    assert five["outcome"] == "missing_data" and five["missing_years"] == ["2022-23", "2021-22"]
