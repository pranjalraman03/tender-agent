"""Load two clearly-labelled DEMO tenders built from the synthetic PDFs in
evals/golden/pdfs/synthetic/, so the whole flow (parse -> index -> live -> match -> eligibility
-> chat) can be tried locally before real tender documents are uploaded.

They live under a separate 'demo' portal and their titles start with "[DEMO]". Indexing needs an
LLM key (LLM_PROVIDER + key); until then they stay parsed and don't appear in the feed.

    uv run python scripts/seed_demo.py           # add / refresh
    uv run python scripts/seed_demo.py --remove  # delete all demo data
"""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from core.db.session import system_transaction
from core.documents import ingest_document
from core.storage import get_storage

PDFS = Path(__file__).resolve().parents[1] / "evals" / "golden" / "pdfs" / "synthetic"
DEMO = [
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


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    async with system_transaction() as s:
        if args.remove:
            await s.execute(
                text(
                    "DELETE FROM jobs WHERE payload->>'tender_id' IN "
                    "(SELECT t.id::text FROM tenders t "
                    "JOIN portals p ON p.id = t.portal_id WHERE p.name = 'demo')"
                )
            )
            await s.execute(
                text(
                    "DELETE FROM tenders WHERE portal_id IN "
                    "(SELECT id FROM portals WHERE name = 'demo')"
                )
            )
            await s.execute(text("DELETE FROM portals WHERE name = 'demo'"))
            print("demo data removed")  # noqa: T201
            return
        portal_id = (
            await s.execute(
                text(
                    "INSERT INTO portals (name, base_url) VALUES ('demo', 'http://localhost:3000') "
                    "ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url RETURNING id"
                )
            )
        ).scalar_one()
        for ref, title, org, pdf, fields in DEMO:
            tender_id = (
                await s.execute(
                    text("""
                INSERT INTO tenders (portal_id, tender_ref, title, org_name, closes_at,
                                     work_state, portal_fields, published_at)
                VALUES (:p, :ref, :title, :org, now() + interval '30 days', 'Delhi',
                        CAST(:fields AS jsonb), now())
                ON CONFLICT (portal_id, tender_ref) DO UPDATE
                  SET closes_at = now() + interval '30 days', lifecycle_status = 'open'
                RETURNING id"""),
                    {
                        "p": portal_id,
                        "ref": ref,
                        "title": title,
                        "org": org,
                        "fields": json.dumps(fields),
                    },
                )
            ).scalar_one()
            result = await ingest_document(
                s, get_storage(), tender_id, pdf, (PDFS / pdf).read_bytes(), source="admin"
            )
            print(f"{ref}: tender {tender_id}, new documents {len(result.new_document_ids)}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
