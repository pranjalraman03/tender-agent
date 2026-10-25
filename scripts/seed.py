"""Seed portals, industries and the NIC -> industry map. Safe to re-run (upserts)."""

import asyncio
import json

from sqlalchemy import text

from core.db.session import system_transaction
from core.reference.industries import INDUSTRIES, NIC_MAP, seed_reference_data

# name, base_url, crawl_cfg. min_interval_s is the gap between requests to the portal.
PORTALS = [
    ("cppp", "https://eprocure.gov.in", {"min_interval_s": 3, "max_detail_pages": 20}),
]


async def main() -> None:
    async with system_transaction() as s:
        for name, base_url, cfg in PORTALS:
            await s.execute(
                text(
                    "INSERT INTO portals (name, base_url, crawl_cfg) "
                    "VALUES (:name, :url, CAST(:cfg AS jsonb)) "
                    "ON CONFLICT (name) DO UPDATE SET base_url = EXCLUDED.base_url, "
                    "crawl_cfg = EXCLUDED.crawl_cfg"
                ),
                {"name": name, "url": base_url, "cfg": json.dumps(cfg)},
            )
        await seed_reference_data(s)
    print(
        f"seeded {len(PORTALS)} portals, {len(INDUSTRIES)} industries, {len(NIC_MAP)} NIC prefixes"
    )  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
