"""Parser tests against saved CPPP pages (no network)."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.crawlers.base import CrawlError
from core.crawlers.cppp import parse_detail, parse_inr, parse_ist, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"
IST = ZoneInfo("Asia/Kolkata")


def test_parse_listing() -> None:
    items = parse_listing((FIXTURES / "cppp_home.html").read_text(errors="ignore"))
    assert len(items) >= 5
    first = items[0]
    assert first.title.startswith("Balance works for the upgradation of the Seldoh")
    assert first.reference_no == "RW/NH-12014/ 53/2026-MAH/ZONE-WEST"
    assert first.closes_at == datetime(2026, 12, 8, 17, 0, tzinfo=IST)
    assert first.detail_url.startswith("https://eprocure.gov.in/eprocure/app?component=")
    assert all(i.closes_at is None or i.closes_at.tzinfo is not None for i in items)


def test_parse_detail() -> None:
    d = parse_detail((FIXTURES / "cppp_detail.html").read_text(errors="ignore"))
    assert d.tender_ref == "2026_MoRTH_931631_1"
    assert d.org_name == "Ministry of Road Transport and Highways"
    assert d.value_inr == Decimal("1495700000")
    assert d.emd_inr == Decimal("15000000")
    assert d.published_at == datetime(2026, 10, 24, 18, 55, tzinfo=IST)
    assert d.closes_at == datetime(2026, 12, 8, 17, 0, tzinfo=IST)
    assert d.raw["Pincode"] == "442104"


def test_parse_detail_rejects_stale_session_page() -> None:
    with pytest.raises(CrawlError):
        parse_detail("<html><title>Stale Session</title></html>")


def test_parse_helpers() -> None:
    assert parse_inr("1,50,00,000") == Decimal("15000000")
    assert parse_inr("NA") is None
    assert parse_ist("NA") is None
    assert parse_ist("29-Oct-2026 03:00 PM") == datetime(2026, 10, 29, 15, 0, tzinfo=IST)
