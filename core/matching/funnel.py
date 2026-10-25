"""Matching funnel (CLAUDE.md "Matching funnel").

1. Hard filters in SQL on live_tenders: industries overlap, work state in the profile's
   states (or a central tender), value within what the turnover supports.
2. Similarity in the same query: ORDER BY scope_embedding <=> profile_embedding LIMIT 50.
   Results go into `matches` as stage 'prefiltered' and are visible immediately.
3. fit_check jobs (the agent) for the top N, cached per profile version.
Reverse matching (new tender -> profiles) uses the same filters with the roles swapped.
Only confirmed profiles are ever used (rule 10).
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.config import get_settings


def max_tender_value(turnover: Decimal | float | None) -> Decimal | None:
    if turnover is None or turnover <= 0:
        return None
    return Decimal(str(turnover)) / Decimal(str(get_settings().match_min_turnover_ratio))


async def _upsert_prefiltered(
    session: AsyncSession, org_id: uuid.UUID, tender_id: int, score: float
) -> None:
    # Never downgrade a match the agent already checked; just refresh its score.
    await session.execute(
        text("""
            INSERT INTO matches (org_id, tender_id, score, stage, updated_at)
            VALUES (:o, :t, :score, 'prefiltered', now())
            ON CONFLICT (org_id, tender_id) DO UPDATE SET score = EXCLUDED.score
        """),
        {"o": org_id, "t": tender_id, "score": score},
    )


async def _enqueue_fit_check(
    session: AsyncSession, org_id: uuid.UUID, tender_id: int, version: int
) -> None:
    await queue.enqueue(
        session,
        "fit_check",
        {"org_id": str(org_id), "tender_id": tender_id},
        f"fit_check:{org_id}:{tender_id}:v{version}",
    )


async def match_profile(session: AsyncSession, profile: dict[str, Any]) -> list[tuple[int, float]]:
    """Stages 1-2 for one confirmed profile; enqueues stage 3. Returns (tender_id, score)."""
    s = get_settings()
    rows = (
        await session.execute(
            text("""
            SELECT t.id, 1 - (t.scope_embedding <=> p.profile_embedding) AS score
            FROM live_tenders t, company_profiles p
            WHERE p.id = :pid
              AND t.scope_embedding IS NOT NULL
              AND t.industries && p.industries
              AND (t.work_state = ANY(p.states) OR t.is_central)
              AND (t.value_inr IS NULL OR CAST(:max_value AS numeric) IS NULL
                   OR t.value_inr <= :max_value)
            ORDER BY t.scope_embedding <=> p.profile_embedding
            LIMIT :n
        """),
            {
                "pid": profile["id"],
                "max_value": max_tender_value(profile["annual_turnover_inr"]),
                "n": s.match_shortlist,
            },
        )
    ).all()
    for i, r in enumerate(rows):
        await _upsert_prefiltered(session, profile["org_id"], r.id, float(r.score))
        if i < s.match_fit_check_top:
            await _enqueue_fit_check(session, profile["org_id"], r.id, int(profile["version"]))
    return [(int(r.id), float(r.score)) for r in rows]


async def match_tender(session: AsyncSession, tender_id: int) -> list[tuple[uuid.UUID, float]]:
    """Reverse funnel: the confirmed profiles closest to one live tender."""
    s = get_settings()
    rows = (
        await session.execute(
            text("""
            WITH latest AS (
                SELECT DISTINCT ON (org_id) *
                FROM company_profiles
                WHERE confirmed_at IS NOT NULL
                ORDER BY org_id, version DESC
            )
            SELECT p.org_id, p.version,
                   1 - (p.profile_embedding <=> t.scope_embedding) AS score
            FROM live_tenders t, latest p
            WHERE t.id = :t
              AND p.profile_embedding IS NOT NULL
              AND t.industries && p.industries
              AND (t.work_state = ANY(p.states) OR t.is_central)
              AND (t.value_inr IS NULL OR p.annual_turnover_inr IS NULL
                   OR t.value_inr * :ratio <= p.annual_turnover_inr)
            ORDER BY p.profile_embedding <=> t.scope_embedding
            LIMIT :n
        """),
            {"t": tender_id, "ratio": s.match_min_turnover_ratio, "n": s.match_shortlist},
        )
    ).all()
    for i, r in enumerate(rows):
        await _upsert_prefiltered(session, r.org_id, tender_id, float(r.score))
        if i < s.match_fit_check_top:
            await _enqueue_fit_check(session, r.org_id, tender_id, int(r.version))
    return [(r.org_id, float(r.score)) for r in rows]


def profile_embedding_text(profile: dict[str, Any]) -> str:
    projects = "; ".join(p.get("title", "") for p in (profile.get("past_projects") or []))
    return "\n".join(
        filter(
            None,
            [
                profile.get("description"),
                "Industries: " + ", ".join(profile.get("industries") or []),
                "Certifications: " + ", ".join(profile.get("certifications") or []),
                f"Past projects: {projects}" if projects else None,
            ],
        )
    )
