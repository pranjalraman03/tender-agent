import json
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.jobs import extract_profile
from core.net.safe_fetch import FetchResult
from core.profiles import website
from core.profiles.service import (
    ProfileError,
    apply_udyam,
    confirm,
    get_draft,
    start_from_website,
    update_draft,
)
from core.profiles.udyam import NotUdyamCertificate, parse_udyam_text
from core.reference.industries import seed_reference_data
from core.storage import LocalStorage
from tests.parsing.samples import text_pdf

SM = async_sessionmaker[AsyncSession]

UDYAM_TEXT = """UDYAM REGISTRATION CERTIFICATE
UDYAM REGISTRATION NUMBER UDYAM-DL-08-0012345
NAME OF ENTERPRISE M/S BRIGHTLINE ELECTRICALS
TYPE OF ENTERPRISE SNo. Classification Year Enterprise Type Classification Date
1 2023-24 Micro 01/07/2023
2 2025-26 Small 10/05/2025
3 2024-25 Small 15/04/2024
MAJOR ACTIVITY SERVICES
OFFICIAL ADDRESS OF ENTERPRISE Plot 12, Sector 7 City NEW DELHI State DELHI Pin 110075
DATE OF INCORPORATION / REGISTRATION OF ENTERPRISE 12/05/2016
NATIONAL INDUSTRY CLASSIFICATION CODE(S)
SNo. NIC 2 Digit NIC 4 Digit NIC 5 Digit Activity
1 43 - Specialised construction activities 4321 - Electrical installation 43211 - Installation of electrical wiring and fittings Services
"""


def test_parse_udyam_text() -> None:
    d = parse_udyam_text(UDYAM_TEXT)
    assert d.udyam_number == "UDYAM-DL-08-0012345"
    assert d.msme_category == "small"  # latest year (2025-26) wins
    assert d.nic_codes == ["43211"]
    assert d.major_activity == "Services"
    assert d.incorporated_on == date(2016, 5, 12)
    assert d.years_in_business(date(2026, 10, 25)) == 10
    assert d.states == ["Delhi"]


def test_parse_udyam_rejects_other_documents() -> None:
    with pytest.raises(NotUdyamCertificate):
        parse_udyam_text("GST registration certificate ...")


async def _org(sm: SM) -> uuid.UUID:
    org = uuid.uuid4()
    async with sm() as s, s.begin():
        await seed_reference_data(s)
        await s.execute(text("INSERT INTO orgs (id, name) VALUES (:o, 'My company')"), {"o": org})
    return org


async def test_profile_flow_udyam_edit_confirm(sessionmaker: SM, tmp_path: Path) -> None:
    org = await _org(sessionmaker)
    storage = LocalStorage(str(tmp_path))
    async with sessionmaker() as s, s.begin():
        await apply_udyam(s, storage, org, text_pdf([UDYAM_TEXT]))
        draft = await get_draft(s, org)
    assert draft is not None and draft["version"] == 1
    assert draft["industries"] == ["electrical_works"] and draft["msme_category"] == "small"
    assert draft["field_sources"]["nic_codes"][0]["udyam_number"] == "UDYAM-DL-08-0012345"
    assert draft["incorporated_on"] == date(2016, 5, 12)  # from the certificate

    async with sessionmaker() as s, s.begin():
        with pytest.raises(ProfileError):
            await update_draft(s, org, {"industries": ["not_a_real_industry"]})
    async with sessionmaker() as s, s.begin():
        with pytest.raises(ProfileError):
            await update_draft(
                s, org, {"turnover_by_year": [{"financial_year": "2024-27", "turnover_inr": 1}]}
            )
    async with sessionmaker() as s, s.begin():
        updated = await update_draft(
            s,
            org,
            {
                "turnover_by_year": [
                    {"financial_year": "FY 2023-24", "turnover_inr": 2700000},
                    {"financial_year": "2024-2025", "turnover_inr": 3100000},
                ],
                "states": ["Delhi", "Haryana"],
            },
        )
        version = await confirm(s, org)
    # Labels normalised, newest first, user-entered rows marked as such; latest year mirrored.
    assert [r["financial_year"] for r in updated["turnover_by_year"]] == ["2024-25", "2023-24"]
    assert updated["turnover_by_year"][0]["source"] == {"source": "user"}
    assert updated["annual_turnover_inr"] == 3100000
    assert version == 1

    # Editing after confirmation creates version 2 from version 1; v1 stays untouched.
    async with sessionmaker() as s, s.begin():
        v2 = await update_draft(s, org, {"description": "We maintain street lights."})
        jobs = (await s.execute(text("SELECT idempotency_key FROM jobs"))).scalars().all()
        v1 = (
            await s.execute(
                text(
                    "SELECT description, confirmed_at FROM company_profiles "
                    "WHERE org_id = :o AND version = 1"
                ),
                {"o": org},
            )
        ).one()
    assert v2["version"] == 2 and len(v2["turnover_by_year"]) == 2  # copied from v1
    assert v1.description is None and v1.confirmed_at is not None
    assert jobs == [f"match_profile:{org}:v1"]


def test_page_text_strips_scripts_and_collects_links() -> None:
    html = (
        "<html><head><script>alert(1)</script></head><body><h1>Brightline</h1>"
        "<p>ISO 9001 certified</p><a href='/about-us'>About</a></body></html>"
    )
    body, links = website.page_text(html)
    assert "alert" not in body and "ISO 9001 certified" in body and links == ["/about-us"]


class FakeClaude:
    async def create(self, ctx: Any, **kw: Any) -> tuple[Any, Any]:
        out = {
            "company_name": "Brightline Electricals",
            "description": "Street lighting AMC.",
            "industries": ["electrical_works"],
            "states": ["Delhi"],
            "certifications": ["ISO 9001"],
            "past_projects": [],
            "years_in_business": None,
            "annual_turnover_inr": None,
            "sources": [
                {
                    "field": "certifications",
                    "url": "https://site.test/about-us",
                    "quote": "ISO 9001 certified",
                },
                {"field": "description", "url": "https://elsewhere.test/", "quote": "made up"},
            ],
        }
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))]), None


async def test_extract_profile_job_fills_only_empty_fields(
    sessionmaker: SM, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _org(sessionmaker)
    pages = {
        "https://site.test": "<body><p>Welcome</p><a href='/about-us'>About</a>"
        "<a href='https://other.test/x'>x</a></body>",
        "https://site.test/about-us": "<body><p>ISO 9001 certified</p></body>",
    }

    async def fake_get(url: str, **kw: Any) -> FetchResult:
        return FetchResult(url, 200, "text/html", pages[url.rstrip("/")].encode())

    monkeypatch.setattr(website, "safe_get", fake_get)
    monkeypatch.setattr(extract_profile, "get_claude", FakeClaude)
    async with sessionmaker() as s, s.begin():
        profile_id = await start_from_website(s, org, "https://site.test")
        await update_draft(s, org, {"states": ["Haryana"]})  # user already chose states
    async with sessionmaker() as s, s.begin():
        await extract_profile.handle({"org_id": str(org), "profile_id": profile_id}, s)
        draft = await get_draft(s, org)
        name = (await s.execute(text("SELECT name FROM orgs WHERE id = :o"), {"o": org})).scalar()
    assert draft is not None
    assert draft["certifications"] == ["ISO 9001"] and draft["states"] == ["Haryana"]
    assert draft["field_sources"]["certifications"][0]["url"] == "https://site.test/about-us"
    # A source pointing at a page that was never fetched is discarded.
    assert draft["field_sources"]["description"] == [{"source": "website"}]
    assert name == "Brightline Electricals"
