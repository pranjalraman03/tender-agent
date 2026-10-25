"""Reading company profiles. Matching and the agent only ever use confirmed profiles
(CLAUDE.md rule 10)."""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROFILE_FIELDS = (
    "description",
    "industries",
    "nic_codes",
    "msme_category",
    "states",
    "annual_turnover_inr",
    "years_in_business",
    "is_msme",
    "certifications",
    "past_projects",
)


async def get_confirmed_profile(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text("""
                SELECT o.name AS company_name, p.*
                FROM company_profiles p JOIN orgs o ON o.id = p.org_id
                WHERE p.org_id = :org AND p.confirmed_at IS NOT NULL
                ORDER BY p.version DESC LIMIT 1
            """),
                {"org": org_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def profile_for_agent(profile: dict[str, Any]) -> dict[str, Any]:
    """The fields the eligibility agent may see (no embeddings, no internal ids)."""
    out: dict[str, Any] = {"company_name": profile["company_name"]}
    for key in PROFILE_FIELDS:
        value = profile.get(key)
        out[key] = str(value) if key == "annual_turnover_inr" and value is not None else value
    return out
