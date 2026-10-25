"""extract_profile job: draft profile fields from the company website (SSRF-safe fetch +
fast model). Only fills fields that are still empty, so Udyam data and the user's own edits
are never overwritten."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.claude import CallContext, Claude
from core.net.safe_fetch import FetchError, UnsafeURL
from core.profiles.website import extract_from_pages, fetch_site, field_sources

log = structlog.get_logger()


def get_claude() -> Claude:  # replaced in tests
    return Claude()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    org_id = uuid.UUID(str(payload["org_id"]))
    profile_id = int(payload["profile_id"])
    draft = (
        (
            await session.execute(
                text(
                    "SELECT * FROM company_profiles WHERE id = :id AND org_id = :o "
                    "AND confirmed_at IS NULL"
                ),
                {"id": profile_id, "o": org_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if draft is None or not draft["website_url"]:
        log.info("extract_profile_skipped", profile_id=profile_id)
        return
    try:
        pages = await fetch_site(draft["website_url"])
    except (FetchError, UnsafeURL) as exc:
        # The user's URL is unusable; record it and stop (retrying won't help).
        sources = {
            **(draft["field_sources"] or {}),
            "_website_error": [{"source": "website", "error": str(exc)}],
        }
        await session.execute(
            text("UPDATE company_profiles SET field_sources = CAST(:s AS jsonb) WHERE id = :id"),
            {"s": json.dumps(sources), "id": profile_id},
        )
        log.info("extract_profile_fetch_failed", profile_id=profile_id, error=str(exc))
        return

    allowed = list(
        (await session.execute(text("SELECT slug FROM industries ORDER BY slug"))).scalars()
    )
    extracted, _ = await extract_from_pages(
        get_claude(),
        pages,
        allowed,
        CallContext(purpose="extract_profile", org_id=org_id, trace_id=f"profile:{profile_id}"),
    )

    sources = dict(draft["field_sources"] or {})
    sources.pop("_website_error", None)
    web_sources = field_sources(extracted)
    updates: dict[str, Any] = {}
    candidates = {
        "description": extracted.description,
        "industries": extracted.industries,
        "states": extracted.states,
        "certifications": extracted.certifications,
        "past_projects": [p.model_dump() for p in extracted.past_projects],
        "years_in_business": extracted.years_in_business,
        "annual_turnover_inr": extracted.annual_turnover_inr,
    }
    for field, value in candidates.items():
        if value in (None, [], "") or draft[field] not in (None, [], ""):
            continue
        updates[field] = value
        sources[field] = web_sources.get(field, [{"source": "website"}])
    await session.execute(
        text("""
            UPDATE company_profiles SET
              description = coalesce(:description, description),
              industries = coalesce(:industries, industries),
              states = coalesce(:states, states),
              certifications = coalesce(:certifications, certifications),
              past_projects = coalesce(CAST(:past_projects AS jsonb), past_projects),
              years_in_business = coalesce(:years_in_business, years_in_business),
              annual_turnover_inr = coalesce(:annual_turnover_inr, annual_turnover_inr),
              field_sources = CAST(:sources AS jsonb)
            WHERE id = :id
        """),
        {
            "id": profile_id,
            "sources": json.dumps(sources),
            "description": updates.get("description"),
            "industries": updates.get("industries"),
            "states": updates.get("states"),
            "certifications": updates.get("certifications"),
            "past_projects": json.dumps(updates["past_projects"])
            if "past_projects" in updates
            else None,
            "years_in_business": updates.get("years_in_business"),
            "annual_turnover_inr": updates.get("annual_turnover_inr"),
        },
    )
    if extracted.company_name:
        await session.execute(
            text("UPDATE orgs SET name = :n WHERE id = :o AND name IN ('', 'My company')"),
            {"n": extracted.company_name, "o": org_id},
        )
    log.info(
        "extract_profile_done", profile_id=profile_id, pages=len(pages), filled=sorted(updates)
    )
