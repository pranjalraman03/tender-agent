"""match_profile job: embed a newly confirmed profile, run funnel stages 1-2, enqueue fit_check
for the top tenders."""

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.embeddings import embed, to_pgvector
from core.matching.funnel import match_profile, profile_embedding_text
from core.profiles.store import get_confirmed_profile

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    org_id = uuid.UUID(str(payload["org_id"]))
    profile = await get_confirmed_profile(session, org_id)
    if profile is None:
        log.info("match_profile_skipped_no_confirmed_profile", org_id=str(org_id))
        return
    if int(payload.get("version", profile["version"])) != int(profile["version"]):
        log.info("match_profile_skipped_newer_version", org_id=str(org_id))
        return
    if profile["profile_embedding"] is None:
        (vec,) = await embed([profile_embedding_text(profile)], "document")
        await session.execute(
            text(
                "UPDATE company_profiles SET profile_embedding = CAST(:v AS vector) WHERE id = :id"
            ),
            {"v": to_pgvector(vec), "id": profile["id"]},
        )
    results = await match_profile(session, profile)
    log.info(
        "match_profile_done",
        org_id=str(org_id),
        version=profile["version"],
        shortlisted=len(results),
    )
