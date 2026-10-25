"""The signed-in org's matches (live tenders only) and eligibility reports."""

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import User, UserDB
from apps.api.routes.tenders import card
from apps.api.schemas import ClauseOut, FindingOut, MatchOut, MatchUpdate, ReportOut
from core.db.session import get_sessionmaker, set_org_context

router = APIRouter(tags=["matches"])
STREAM_SECONDS = 600
POLL_SECONDS = 3

MATCH_QUERY = """
    SELECT t.id, t.title, t.org_name, t.work_state, t.is_central, t.industries, t.value_inr,
           t.emd_inr, t.closes_at, t.published_at, t.summary,
           m.score, m.stage, m.fit, m.user_state, m.needs_recheck, m.updated_at,
           r.verdict
    FROM matches m
    JOIN live_tenders t ON t.id = m.tender_id
    LEFT JOIN LATERAL (
        SELECT verdict FROM eligibility_reports er
        WHERE er.org_id = m.org_id AND er.tender_id = m.tender_id
        ORDER BY er.profile_version DESC LIMIT 1
    ) r ON true
    WHERE m.org_id = :o
      AND (CAST(:since AS timestamptz) IS NULL OR m.updated_at > :since)
      AND (CAST(:fit AS text[]) IS NULL OR m.fit = ANY(:fit))
      AND (CAST(:states AS text[]) IS NULL OR t.work_state = ANY(:states) OR t.is_central)
      AND (CAST(:industries AS text[]) IS NULL OR t.industries && :industries)
      AND (:include_dismissed OR m.user_state IS DISTINCT FROM 'dismissed')
    ORDER BY CASE m.fit WHEN 'good' THEN 0 WHEN 'possible' THEN 1
                        WHEN 'not_eligible' THEN 3 ELSE 2 END,
             m.score DESC NULLS LAST, t.closes_at
    LIMIT 200
"""


def _match(row: Any) -> MatchOut:
    return MatchOut(
        tender=card(row),
        score=row["score"],
        stage=row["stage"],
        fit=row["fit"],
        user_state=row["user_state"],
        needs_recheck=row["needs_recheck"],
        verdict=row["verdict"],
        updated_at=row["updated_at"],
    )


async def _query(db: AsyncSession, org_id: Any, **filters: Any) -> list[MatchOut]:
    params = {
        "o": org_id,
        "since": None,
        "fit": None,
        "states": None,
        "industries": None,
        "include_dismissed": False,
        **filters,
    }
    rows = (await db.execute(text(MATCH_QUERY), params)).mappings().all()
    return [_match(r) for r in rows]


@router.get("/matches")
async def list_matches(
    user: User,
    db: UserDB,
    fit: Annotated[list[str] | None, Query()] = None,
    state: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    include_dismissed: bool = False,
) -> list[MatchOut]:
    return await _query(
        db,
        user.org_id,
        fit=fit,
        states=state,
        industries=industry,
        include_dismissed=include_dismissed,
    )


@router.patch("/matches/{tender_id}")
async def update_match(tender_id: int, body: MatchUpdate, user: User, db: UserDB) -> MatchOut:
    updated = (
        await db.execute(
            text(
                "UPDATE matches SET user_state = :s, updated_at = now() "
                "WHERE org_id = :o AND tender_id = :t RETURNING tender_id"
            ),
            {"s": body.user_state, "o": user.org_id, "t": tender_id},
        )
    ).first()
    if updated is None:
        raise HTTPException(404, "match not found")
    rows = await _query(db, user.org_id, include_dismissed=True)
    found = next((m for m in rows if m.tender.id == tender_id), None)
    if found is None:
        raise HTTPException(404, "tender no longer open")
    return found


@router.get("/matches/stream")
async def stream_matches(user: User) -> StreamingResponse:
    """SSE: emits matches as they are created or updated (prefiltered -> agent_checked)."""

    async def events() -> AsyncIterator[str]:
        since = datetime.now(UTC)
        deadline = time.monotonic() + STREAM_SECONDS
        yield "event: ready\ndata: {}\n\n"
        while time.monotonic() < deadline:
            async with get_sessionmaker()() as s, s.begin():
                await set_org_context(s, user.org_id)
                changed = await _query(s, user.org_id, since=since, include_dismissed=True)
            if changed:
                since = max(m.updated_at for m in changed)
                for m in changed:
                    yield f"event: match\ndata: {m.model_dump_json()}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reports/{tender_id}")
async def get_report(tender_id: int, user: User, db: UserDB) -> ReportOut:
    live = (
        await db.execute(text("SELECT 1 FROM live_tenders WHERE id = :t"), {"t": tender_id})
    ).first()
    if not live:
        raise HTTPException(404, "tender not found or no longer open")
    report = (
        (
            await db.execute(
                text(
                    "SELECT * FROM eligibility_reports WHERE org_id = :o AND tender_id = :t "
                    "ORDER BY profile_version DESC LIMIT 1"
                ),
                {"o": user.org_id, "t": tender_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if report is None:
        raise HTTPException(404, "no eligibility report yet")
    current = (
        await db.execute(
            text(
                "SELECT max(version) FROM company_profiles WHERE org_id = :o "
                "AND confirmed_at IS NOT "
                "NULL"
            ),
            {"o": user.org_id},
        )
    ).scalar_one()
    findings = [FindingOut(**f) for f in report["findings"]]
    ids = sorted({i for f in findings for i in f.clause_ids})
    clauses = (
        await db.execute(
            text(
                "SELECT id, document_id, clause_no, section, page_start, page_end, text "
                "FROM clauses "
                "WHERE tender_id = :t AND id = ANY(:ids)"
            ),
            {"t": tender_id, "ids": ids},
        )
    ).mappings()
    return ReportOut(
        tender_id=tender_id,
        profile_version=report["profile_version"],
        verdict=report["verdict"],
        findings=findings,
        clauses=[ClauseOut(**c) for c in clauses],
        model=report["model"],
        created_at=report["created_at"],
        stale=current is not None and report["profile_version"] < current,
    )
