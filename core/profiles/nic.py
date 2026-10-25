"""NIC code -> industry slugs, by longest matching prefix in nic_industry_map."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def industries_for_nic(session: AsyncSession, codes: list[str]) -> list[str]:
    if not codes:
        return []
    rows = (
        await session.execute(text("SELECT nic_prefix, industry_slug FROM nic_industry_map"))
    ).all()
    by_prefix: dict[str, list[str]] = {}
    for r in rows:
        by_prefix.setdefault(r.nic_prefix, []).append(r.industry_slug)
    out: list[str] = []
    for code in codes:
        for n in range(len(code), 1, -1):
            if code[:n] in by_prefix:
                out.extend(s for s in by_prefix[code[:n]] if s not in out)
                break
    return out
