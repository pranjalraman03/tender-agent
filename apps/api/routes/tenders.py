"""Public tender routes. Every query reads live tenders (rule 1): a tender past its
deadline, closed, cancelled or not yet indexed is simply not found."""

from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import text

from apps.api.deps import CurrentUser, MaybeUser, PublicDB, User, UserDB, rate_limit
from apps.api.schemas import (
    ClauseOut,
    DocumentOut,
    IndustryOut,
    Meta,
    TenderCard,
    TenderDetail,
    TenderEventOut,
    TenderPage,
    UploadResult,
)
from core.config import get_settings
from core.documents import InvalidDocument, ingest_document
from core.reference.states import STATES
from core.storage import get_storage

router = APIRouter(tags=["tenders"])

MAX_UPLOAD = 100 * 1024 * 1024


def card(row: Any) -> TenderCard:
    return TenderCard(**{k: row[k] for k in TenderCard.model_fields})


@router.get("/meta")
async def meta(db: PublicDB) -> Meta:
    rows = (await db.execute(text("SELECT slug, name FROM industries ORDER BY name"))).all()
    return Meta(
        industries=[IndustryOut(slug=r.slug, name=r.name) for r in rows],
        states=STATES,
        llm_configured=get_settings().llm_configured,
    )


@router.get("/tenders")
async def list_tenders(
    db: PublicDB,
    user: MaybeUser,
    state: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1, le=500)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> TenderPage:
    params: dict[str, Any] = {
        "include_demo": include_demo(user),
        "states": state,
        "industries": industry,
        "q": q,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    total = (
        await db.execute(
            text("""
        SELECT count(*) FROM live_tenders_incl_demo t
        WHERE (NOT t.is_demo OR :include_demo)
          AND (CAST(:states AS text[]) IS NULL OR t.work_state = ANY(:states) OR t.is_central)
          AND (CAST(:industries AS text[]) IS NULL OR t.industries && :industries)
          AND (CAST(:q AS text) IS NULL
               OR t.title ILIKE '%' || :q || '%' OR t.org_name ILIKE '%' || :q || '%'
               OR t.summary ILIKE '%' || :q || '%')
    """),
            params,
        )
    ).scalar_one()
    rows = (
        (
            await db.execute(
                text("""
        SELECT t.id, t.title, t.org_name, t.work_state, t.is_central, t.industries,
               t.value_inr, t.emd_inr, t.closes_at, t.published_at, t.summary
        FROM live_tenders_incl_demo t
        WHERE (NOT t.is_demo OR :include_demo)
          AND (CAST(:states AS text[]) IS NULL OR t.work_state = ANY(:states) OR t.is_central)
          AND (CAST(:industries AS text[]) IS NULL OR t.industries && :industries)
          AND (CAST(:q AS text) IS NULL
               OR t.title ILIKE '%' || :q || '%' OR t.org_name ILIKE '%' || :q || '%'
               OR t.summary ILIKE '%' || :q || '%')
        ORDER BY t.closes_at ASC, t.id
        LIMIT :limit OFFSET :offset
    """),
                params,
            )
        )
        .mappings()
        .all()
    )
    return TenderPage(items=[card(r) for r in rows], total=total, page=page, page_size=page_size)


def include_demo(user: CurrentUser | None) -> bool:
    """Demo tenders are visible to admins only (they sit in the demo company)."""
    return user is not None and user.is_admin


async def _live_or_404(db: Any, tender_id: int, user: CurrentUser | None) -> Any:
    row = (
        (
            await db.execute(
                text("""
        SELECT t.id, t.title, t.org_name, t.work_state, t.is_central, t.industries,
               t.value_inr, t.emd_inr, t.closes_at, t.published_at, t.summary,
               t.tender_ref, t.source_url, t.portal_fields, p.name AS portal
        FROM live_tenders_incl_demo t JOIN portals p ON p.id = t.portal_id
        WHERE t.id = :t AND (NOT t.is_demo OR :include_demo)
    """),
                {"t": tender_id, "include_demo": include_demo(user)},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "tender not found or no longer open")
    return row


@router.get("/tenders/{tender_id}")
async def get_tender(tender_id: int, db: PublicDB, user: MaybeUser) -> TenderDetail:
    row = await _live_or_404(db, tender_id, user)
    docs = (
        (
            await db.execute(
                text(
                    "SELECT id, filename, page_count, is_scanned, parsed_at FROM tender_documents "
                    "WHERE tender_id = :t ORDER BY id"
                ),
                {"t": tender_id},
            )
        )
        .mappings()
        .all()
    )
    events = (
        (
            await db.execute(
                text(
                    "SELECT kind, detected_at, old_value, new_value FROM tender_events "
                    "WHERE tender_id = :t ORDER BY detected_at"
                ),
                {"t": tender_id},
            )
        )
        .mappings()
        .all()
    )
    return TenderDetail(
        **card(row).model_dump(),
        tender_ref=row["tender_ref"],
        portal=row["portal"],
        source_url=row["source_url"],
        reference_no=row["portal_fields"].get("Tender Reference Number"),
        documents=[DocumentOut(**d) for d in docs],
        events=[TenderEventOut(**e) for e in events],
    )


@router.get("/tenders/{tender_id}/clauses")
async def get_clauses(
    tender_id: int,
    db: PublicDB,
    user: MaybeUser,
    ids: Annotated[list[int], Query(max_length=100)],
) -> list[ClauseOut]:
    await _live_or_404(db, tender_id, user)
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, document_id, clause_no, section, page_start, page_end, text "
                    "FROM clauses WHERE tender_id = :t AND id = ANY(:ids)"
                ),
                {"t": tender_id, "ids": ids},
            )
        )
        .mappings()
        .all()
    )
    return [ClauseOut(**r) for r in rows]


@router.get("/tenders/{tender_id}/documents/{document_id}/file", response_model=None)
async def document_file(
    tender_id: int, document_id: int, db: PublicDB, user: MaybeUser
) -> Response:
    await _live_or_404(db, tender_id, user)
    doc = (
        await db.execute(
            text(
                "SELECT storage_key, filename FROM tender_documents "
                "WHERE id = :d AND tender_id = :t"
            ),
            {"d": document_id, "t": tender_id},
        )
    ).one_or_none()
    if doc is None:
        raise HTTPException(404, "document not found")
    storage = get_storage()
    url = await storage.signed_url(doc.storage_key)
    if url:
        return RedirectResponse(url, status_code=307)
    return Response(
        await storage.get(doc.storage_key),
        media_type="application/pdf",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/tenders/{tender_id}/documents")
async def upload_documents(
    tender_id: int, user: User, db: UserDB, file: Annotated[UploadFile, File()]
) -> UploadResult:
    """A signed-in user adds a document (e.g. a corrigendum) to a live tender."""
    await rate_limit(f"upload:{user.id}", limit=10, window_s=86400)
    await _live_or_404(db, tender_id, user)
    data = await file.read(MAX_UPLOAD + 1)
    try:
        result = await ingest_document(
            db,
            get_storage(),
            tender_id,
            file.filename or "upload",
            data,
            source="user",
            uploaded_by=user.id,
        )
    except InvalidDocument as exc:
        raise HTTPException(422, str(exc)) from exc
    return UploadResult(
        new_documents=len(result.new_document_ids),
        duplicates=result.duplicates,
        skipped_files=result.skipped_files,
    )
