"""fit_check job: run the eligibility agent for one (org, tender) and store the report.

Reports are cached on (org_id, tender_id, profile_version): a re-run for the same profile
version only refreshes the match, unless the match was flagged needs_recheck (a corrigendum
changed eligibility clauses)."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent.loop import run_eligibility
from core.llm.claude import Claude
from core.profiles.store import get_confirmed_profile

log = structlog.get_logger()

FIT_FOR_VERDICT = {
    "eligible": "good",
    "possibly_eligible": "possible",
    "needs_review": "possible",
    "not_eligible": "not_eligible",
}


def get_claude() -> Claude:  # replaced in tests
    return Claude()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    org_id = uuid.UUID(str(payload["org_id"]))
    tender_id = int(payload["tender_id"])

    live = (
        await session.execute(text("SELECT 1 FROM live_tenders WHERE id = :t"), {"t": tender_id})
    ).first()
    if not live:
        log.info("fit_check_skipped_not_live", tender_id=tender_id)
        return
    profile = await get_confirmed_profile(session, org_id)
    if profile is None:
        log.info("fit_check_skipped_no_confirmed_profile", org_id=str(org_id))
        return
    version = int(profile["version"])

    match = (
        await session.execute(
            text("SELECT needs_recheck FROM matches WHERE org_id = :o AND tender_id = :t"),
            {"o": org_id, "t": tender_id},
        )
    ).one_or_none()
    cached = (
        await session.execute(
            text(
                "SELECT verdict FROM eligibility_reports "
                "WHERE org_id = :o AND tender_id = :t AND profile_version = :v"
            ),
            {"o": org_id, "t": tender_id, "v": version},
        )
    ).one_or_none()

    if cached is not None and not (match and match.needs_recheck):
        verdict = cached.verdict
    else:
        result = await run_eligibility(session, get_claude(), tender_id, org_id, profile)
        verdict = result.report.verdict
        await session.execute(
            text("""
                INSERT INTO eligibility_reports (org_id, tender_id, profile_version, verdict,
                                                 findings, model, trace_id)
                VALUES (:o, :t, :v, :verdict, CAST(:findings AS jsonb), :model, :trace)
                ON CONFLICT (org_id, tender_id, profile_version) DO UPDATE
                  SET verdict = EXCLUDED.verdict, findings = EXCLUDED.findings,
                      model = EXCLUDED.model, trace_id = EXCLUDED.trace_id,
                      created_at = now()
            """),
            {
                "o": org_id,
                "t": tender_id,
                "v": version,
                "verdict": verdict,
                "findings": json.dumps([f.model_dump() for f in result.report.findings]),
                "model": ",".join(sorted(result.usage.models)) or "none",
                "trace": result.trace_id,
            },
        )

    await session.execute(
        text("""
            INSERT INTO matches (org_id, tender_id, stage, fit, needs_recheck, updated_at)
            VALUES (:o, :t, 'agent_checked', :fit, false, now())
            ON CONFLICT (org_id, tender_id) DO UPDATE
              SET stage = 'agent_checked', fit = EXCLUDED.fit, needs_recheck = false,
                  updated_at = now()
        """),
        {"o": org_id, "t": tender_id, "fit": FIT_FOR_VERDICT[verdict]},
    )
