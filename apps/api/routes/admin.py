"""Admin routes (admin role only; system DB context). Admin pages may read `tenders`
directly (rule 1 allows it) - e.g. the documents-needed queue lists tenders that aren't live
yet because nobody has uploaded their documents."""

from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import text

from apps.api.deps import Admin, AdminDB
from apps.api.schemas import AdminOverview, DeadJob, JobStat, NeededDocsItem, UploadResult
from core import queue
from core.config import get_settings
from core.documents import InvalidDocument, ingest_document
from core.storage import get_storage

router = APIRouter(prefix="/admin", tags=["admin"])
MAX_UPLOAD = 100 * 1024 * 1024
PORTAL_HOME = {"cppp": "https://eprocure.gov.in/eprocure/app"}


@router.get("/overview")
async def overview(admin: Admin, db: AdminDB) -> AdminOverview:
    jobs = (
        (
            await db.execute(
                text(
                    "SELECT kind, status, count(*) AS count FROM jobs GROUP BY kind, status "
                    "ORDER BY kind, status"
                )
            )
        )
        .mappings()
        .all()
    )
    dead = (
        (
            await db.execute(
                text(
                    "SELECT id, kind, payload, attempts, last_error, updated_at FROM jobs "
                    "WHERE status = 'dead' ORDER BY updated_at DESC LIMIT 20"
                )
            )
        )
        .mappings()
        .all()
    )
    tenders = (
        (
            await db.execute(
                text(
                    "SELECT pipeline_status, lifecycle_status, count(*) AS count FROM tenders "
                    "GROUP BY 1, 2 ORDER BY 1, 2"
                )
            )
        )
        .mappings()
        .all()
    )
    costs = (
        (
            await db.execute(
                text("""
        SELECT date_trunc('day', created_at)::date AS day, purpose, count(*) AS calls,
               sum(cost_usd) AS cost_usd
        FROM llm_calls WHERE created_at > now() - interval '7 days'
        GROUP BY 1, 2 ORDER BY 1 DESC, 4 DESC""")
            )
        )
        .mappings()
        .all()
    )
    evals = (
        (
            await db.execute(
                text(
                    "SELECT id, git_sha, branch, created_at, metrics - 'per_case' AS metrics "
                    "FROM eval_runs ORDER BY id DESC LIMIT 10"
                )
            )
        )
        .mappings()
        .all()
    )
    return AdminOverview(
        jobs=[JobStat(**j) for j in jobs],
        dead=[DeadJob(**d) for d in dead],
        tenders_by_status=[dict(t) for t in tenders],
        llm_cost_7d=[
            {**c, "day": str(c["day"]), "cost_usd": float(c["cost_usd"] or 0)} for c in costs
        ],
        eval_runs=[{**e, "created_at": e["created_at"].isoformat()} for e in evals],
        llm_configured=get_settings().llm_configured,
    )


@router.get("/documents-needed")
async def documents_needed(admin: Admin, db: AdminDB) -> list[NeededDocsItem]:
    """Open tenders with no documents yet, plus indexed tenders with a corrigendum notice
    newer than their latest document. Soonest deadline first."""
    rows = (
        (
            await db.execute(
                text("""
        SELECT t.id, t.title, t.org_name, t.tender_ref, t.closes_at, p.name AS portal,
               t.portal_fields->>'Tender Reference Number' AS reference_no,
               CASE WHEN d.latest IS NULL THEN 'no_documents' ELSE 'corrigendum' END AS reason
        FROM tenders t
        JOIN portals p ON p.id = t.portal_id
        LEFT JOIN LATERAL (SELECT max(created_at) AS latest FROM tender_documents
                           WHERE tender_id = t.id) d ON true
        WHERE t.lifecycle_status IN ('open', 'extended') AND t.closes_at > now()
          AND (d.latest IS NULL
               OR EXISTS (SELECT 1 FROM tender_events e WHERE e.tender_id = t.id
                          AND e.kind = 'corrigendum' AND e.detected_at > d.latest))
        ORDER BY t.closes_at
        LIMIT 200
    """)
            )
        )
        .mappings()
        .all()
    )
    return [
        NeededDocsItem(
            tender_id=r["id"],
            title=r["title"],
            org_name=r["org_name"],
            reference_no=r["reference_no"],
            portal_tender_id=r["tender_ref"],
            closes_at=r["closes_at"],
            reason=r["reason"],
            portal_url=PORTAL_HOME.get(r["portal"], ""),
        )
        for r in rows
    ]


@router.post("/tenders/{tender_id}/documents")
async def admin_upload(
    tender_id: int, admin: Admin, db: AdminDB, file: Annotated[UploadFile, File()]
) -> UploadResult:
    exists = (
        await db.execute(text("SELECT 1 FROM tenders WHERE id = :t"), {"t": tender_id})
    ).first()
    if not exists:
        raise HTTPException(404, "tender not found")
    data = await file.read(MAX_UPLOAD + 1)
    try:
        result = await ingest_document(
            db,
            get_storage(),
            tender_id,
            file.filename or "upload",
            data,
            source="admin",
            uploaded_by=admin.id,
        )
    except InvalidDocument as exc:
        raise HTTPException(422, str(exc)) from exc
    return UploadResult(
        new_documents=len(result.new_document_ids),
        duplicates=result.duplicates,
        skipped_files=result.skipped_files,
    )


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, admin: Admin, db: AdminDB) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                "UPDATE jobs SET status = 'queued', attempts = 0, run_after = now(), "
                "last_error = NULL, "
                "updated_at = now() WHERE id = :id AND status IN ('dead', 'cancelled') "
                "RETURNING id, kind, payload"
            ),
            {"id": job_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "no dead or cancelled job with that id")
    tender_id = row.payload.get("tender_id")
    if row.kind in queue.PIPELINE_KINDS and tender_id is not None:
        await db.execute(
            text(
                "UPDATE tenders SET pipeline_status = 'discovered' "
                "WHERE id = :t AND pipeline_status = 'failed'"
            ),
            {"t": int(tender_id)},
        )
    return {"id": row.id, "status": "queued"}


@router.post("/crawl/{portal}")
async def crawl_now(portal: str, admin: Admin, db: AdminDB) -> dict[str, Any]:
    from datetime import UTC, datetime

    key = f"crawl:{portal}:manual:{datetime.now(UTC):%Y-%m-%dT%H:%M}"
    job_id = await queue.enqueue(db, "crawl", {"portal": portal}, key)
    return {"job_id": job_id, "queued": job_id is not None}
