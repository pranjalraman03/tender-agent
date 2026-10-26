"""Load the admin-only DEMO data: a demo company with a confirmed profile, and two
clearly-labelled demo tenders built from the synthetic PDFs in evals/golden/pdfs/synthetic/.

Demo data is isolated:
- demo tenders (tenders.is_demo) never appear in the public feed or to regular users - the
  live_tenders view excludes them; only admins read them;
- the demo company (orgs.is_demo) is where admins sign in (ADMIN_EMAILS); regular users always
  get a company of their own and never see it;
- matching pairs demo tenders only with the demo company.

Indexing needs an LLM key; until then the demo tenders stay "parsed".

    uv run python scripts/seed_demo.py           # add / refresh
    uv run python scripts/seed_demo.py --remove  # delete all demo data
"""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from core import queue
from core.db.session import system_transaction
from core.documents import ingest_document
from core.storage import get_storage

PDFS = Path(__file__).resolve().parents[1] / "evals" / "golden" / "pdfs" / "synthetic"
DEMO_TENDERS = [
    (
        "DEMO-DDA-STREETLIGHTS",
        "[DEMO] Annual maintenance of street lights, Dwarka Sectors 5-12",
        "Delhi Development Authority (demo)",
        "dda_streetlights.pdf",
        {"Tender Reference Number": "99/EE(E)/SYN/2026-27", "Pincode": "110075"},
    ),
    (
        "DEMO-AIIMS-OPHTHALMOSCOPE",
        "[DEMO] Supply of 18 coaxial indirect ophthalmoscopes",
        "AIIMS (demo)",
        "aiims_ophthalmoscope.pdf",
        {"Tender Reference Number": "SYN/AIIMS/2026/042", "Pincode": "110029"},
    ),
]
DEMO_COMPANY = "Brightline Electricals (demo)"
DEMO_PROFILE = {
    "description": "Electrical contractor doing annual maintenance of street lighting and "
    "high-mast lighting for municipal bodies in Delhi NCR.",
    "industries": ["electrical_works"],
    "states": ["Delhi", "Haryana"],
    "msme_category": "small",
    "certifications": [
        "CPWD registration - Class IV (Electrical)",
        "Electrical contractor licence, Govt of NCT of Delhi",
        "Udyam registration",
    ],
    "past_projects": [
        {
            "title": "Maintenance of street lights, Rohini Sector 3-9",
            "client": "MCD",
            "value_inr": 2600000,
            "year": 2023,
        },
        {
            "title": "Outdoor lighting AMC, Janakpuri",
            "client": "DDA",
            "value_inr": 2550000,
            "year": 2025,
        },
    ],
    "turnover_by_year": [
        {"financial_year": "2025-26", "turnover_inr": 3800000, "source": {"source": "user"}},
        {"financial_year": "2024-25", "turnover_inr": 3100000, "source": {"source": "user"}},
        {"financial_year": "2023-24", "turnover_inr": 2700000, "source": {"source": "user"}},
    ],
    "incorporated_on": date(2018, 4, 10),
}


async def remove() -> None:
    async with system_transaction() as s:
        await s.execute(
            text(
                "DELETE FROM jobs WHERE payload->>'tender_id' IN "
                "(SELECT id::text FROM tenders WHERE is_demo) "
                "OR payload->>'org_id' IN (SELECT id::text FROM orgs WHERE is_demo)"
            )
        )
        await s.execute(text("DELETE FROM tenders WHERE is_demo"))
        await s.execute(text("DELETE FROM portals WHERE name = 'demo'"))
        # Admins in the demo company get a company of their own before it is deleted.
        admins = (
            await s.execute(
                text("SELECT u.id FROM users u JOIN orgs o ON o.id = u.org_id WHERE o.is_demo")
            )
        ).scalars()
        for user_id in list(admins):
            org_id = (
                await s.execute(text("INSERT INTO orgs (name) VALUES ('My company') RETURNING id"))
            ).scalar_one()
            await s.execute(
                text("UPDATE users SET org_id = :o WHERE id = :u"), {"o": org_id, "u": user_id}
            )
        await s.execute(text("DELETE FROM orgs WHERE is_demo"))
    print("demo data removed")  # noqa: T201


async def add() -> None:
    async with system_transaction() as s:
        org_id = (
            await s.execute(text("SELECT id FROM orgs WHERE is_demo ORDER BY created_at LIMIT 1"))
        ).scalar_one_or_none()
        if org_id is None:
            org_id = (
                await s.execute(
                    text("INSERT INTO orgs (name, is_demo) VALUES (:n, true) RETURNING id"),
                    {"n": DEMO_COMPANY},
                )
            ).scalar_one()
            p = DEMO_PROFILE
            await s.execute(
                text("""
                INSERT INTO company_profiles (
                    org_id, version, description, industries, states, msme_category, is_msme,
                    certifications, past_projects, turnover_by_year, incorporated_on,
                    annual_turnover_inr, years_in_business, confirmed_at)
                VALUES (:o, 1, :d, :ind, :st, :cat, true, :cert, CAST(:pp AS jsonb),
                        CAST(:tby AS jsonb), :inc, :latest, :years, now())
            """),
                {
                    "o": org_id,
                    "d": p["description"],
                    "ind": p["industries"],
                    "st": p["states"],
                    "cat": p["msme_category"],
                    "cert": p["certifications"],
                    "pp": json.dumps(p["past_projects"]),
                    "tby": json.dumps(p["turnover_by_year"]),
                    "inc": p["incorporated_on"],
                    "latest": 3800000,
                    "years": 8,
                },
            )
            await queue.enqueue(
                s,
                "match_profile",
                {"org_id": str(org_id), "version": 1},
                f"match_profile:{org_id}:v1",
            )
        # Existing admins move into the demo company (new admins land there on sign-in).
        moved = (
            (
                await s.execute(
                    text(
                        "UPDATE users SET org_id = :o "
                        "WHERE role = 'admin' AND org_id <> :o RETURNING email"
                    ),
                    {"o": org_id},
                )
            )
            .scalars()
            .all()
        )

        portal_id = (
            await s.execute(
                text(
                    "INSERT INTO portals (name, base_url) VALUES ('demo', 'http://localhost:3000') "
                    "ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url RETURNING id"
                )
            )
        ).scalar_one()
        for ref, title, org_name, pdf, fields in DEMO_TENDERS:
            tender_id = (
                await s.execute(
                    text("""
                INSERT INTO tenders (portal_id, tender_ref, title, org_name, closes_at,
                                     work_state, portal_fields, published_at, is_demo)
                VALUES (:p, :ref, :title, :org, now() + interval '30 days', 'Delhi',
                        CAST(:fields AS jsonb), now(), true)
                ON CONFLICT (portal_id, tender_ref) DO UPDATE
                  SET closes_at = now() + interval '30 days', lifecycle_status = 'open',
                      is_demo = true
                RETURNING id"""),
                    {
                        "p": portal_id,
                        "ref": ref,
                        "title": title,
                        "org": org_name,
                        "fields": json.dumps(fields),
                    },
                )
            ).scalar_one()
            result = await ingest_document(
                s, get_storage(), tender_id, pdf, (PDFS / pdf).read_bytes(), source="admin"
            )
            new_docs = len(result.new_document_ids)
            print(f"{ref}: tender {tender_id}, new documents {new_docs}")  # noqa: T201
    print(f"demo company {org_id}; admins moved in: {list(moved) or 'none yet'}")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    asyncio.run(remove() if parser.parse_args().remove else add())


if __name__ == "__main__":
    main()
