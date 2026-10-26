import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.jobs import extract_financials
from core.profiles.financials import CertificateExtraction, TurnoverRow, merge_turnover, verify_rows
from core.profiles.service import ProfileError, add_ca_certificate, get_draft
from core.storage import LocalStorage
from tests.parsing.samples import text_pdf

SM = async_sessionmaker[AsyncSession]

CERT = """TURNOVER CERTIFICATE
This is to certify that the turnover of M/s Brightline Electricals, as per audited accounts, is:
Financial Year 2023-24 : Rs. 27,00,000
Financial Year 2024-25 : Rs. 31,00,000
Financial Year 2025-26 : Rs. 38,00,000
For Sharma & Co., Chartered Accountants. Date: 15/07/2026"""


def test_verify_rows_drops_unverifiable_figures() -> None:
    extraction = CertificateExtraction(
        is_turnover_certificate=True,
        issued_by="Sharma & Co.",
        certificate_date="15/07/2026",
        rows=[
            TurnoverRow(
                financial_year="2024-25",
                turnover_inr=3100000,
                quote="Financial Year 2024-25 : Rs. 31,00,000",
            ),
            TurnoverRow(
                financial_year="2022-23",
                turnover_inr=2500000,
                quote="Financial Year 2022-23 : Rs. 25,00,000",
            ),  # invented: not in text
            TurnoverRow(financial_year="2023", turnover_inr=1, quote="x"),  # bad FY
        ],
    )
    rows, rejected = verify_rows(extraction, CERT)
    assert [r["financial_year"] for r in rows] == ["2024-25"]
    assert len(rejected) == 2 and any("quote not found" in r for r in rejected)


def test_merge_newer_certificate_replaces_same_year_keeps_others() -> None:
    existing = [
        {"financial_year": "2021-22", "turnover_inr": 1},
        {"financial_year": "2024-25", "turnover_inr": 2},
    ]
    merged = merge_turnover(
        existing,
        [{"financial_year": "2024-25", "turnover_inr": 9, "quote": "q"}],
        {"source": "ca_certificate"},
    )
    assert [(r["financial_year"], r["turnover_inr"]) for r in merged] == [
        ("2024-25", 9),
        ("2021-22", 1),
    ]


class FakeClaude:
    async def create(self, ctx: Any, **kw: Any) -> tuple[Any, Any]:
        out = {
            "is_turnover_certificate": True,
            "issued_by": "Sharma & Co.",
            "certificate_date": "15/07/2026",
            "rows": [
                {"financial_year": fy, "turnover_inr": v, "quote": f"Financial Year {fy} : {q}"}
                for fy, v, q in [
                    ("2025-26", 3800000, "Rs. 38,00,000"),
                    ("2024-25", 3100000, "Rs. 31,00,000"),
                    ("2023-24", 2700000, "Rs. 27,00,000"),
                ]
            ],
        }
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))]), None


async def test_ca_certificate_upload_and_extraction(
    sessionmaker: SM, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(str(tmp_path))
    monkeypatch.setattr(extract_financials, "get_storage", lambda: storage)
    monkeypatch.setattr(extract_financials, "get_claude", FakeClaude)
    org = uuid.uuid4()
    async with sessionmaker() as s, s.begin():
        await s.execute(text("INSERT INTO orgs (id, name) VALUES (:o, 'x')"), {"o": org})
        with pytest.raises(ProfileError):
            await add_ca_certificate(s, storage, org, "cert.txt", b"not a pdf")
        pdf = text_pdf([CERT])
        doc_id = await add_ca_certificate(s, storage, org, "cert.pdf", pdf)
        again = await add_ca_certificate(s, storage, org, "cert.pdf", pdf)
        payloads = (
            (await s.execute(text("SELECT payload FROM jobs WHERE kind = 'extract_financials'")))
            .scalars()
            .all()
        )
    assert doc_id == again and len(payloads) == 1  # same file twice: one document, one job

    async with sessionmaker() as s, s.begin():
        await extract_financials.handle(payloads[0], s)
        draft = await get_draft(s, org)
        extracted = (await s.execute(text("SELECT extracted FROM company_documents"))).scalar()
    assert draft is not None
    assert [r["financial_year"] for r in draft["turnover_by_year"]] == [
        "2025-26",
        "2024-25",
        "2023-24",
    ]
    assert draft["turnover_by_year"][0]["source"]["document_id"] == doc_id
    assert float(draft["annual_turnover_inr"]) == 3800000
    assert extracted["issued_by"] == "Sharma & Co." and extracted["rejected"] == []
