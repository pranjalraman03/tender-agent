"""Signed-in user's org, company profile onboarding and review."""

from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import User, UserDB, rate_limit
from apps.api.schemas import (
    CompanyDocumentOut,
    Me,
    OrgOut,
    ProfileOut,
    ProfileState,
    ProfileUpdate,
    UdyamOut,
    WebsiteRequest,
)
from core.profiles import service
from core.profiles.udyam import NotUdyamCertificate
from core.storage import get_storage

router = APIRouter(tags=["profile"])
MAX_UDYAM_BYTES = 10 * 1024 * 1024


async def _profile_out(db: AsyncSession, row: dict[str, Any] | None) -> ProfileOut | None:
    if row is None:
        return None
    pending = (
        await db.execute(
            text(
                "SELECT 1 FROM jobs WHERE kind IN ('extract_profile', 'extract_financials') "
                "AND status IN ('queued', 'running') "
                "AND (payload->>'profile_id')::bigint = :id"
            ),
            {"id": row["id"]},
        )
    ).first() is not None
    data = {k: row[k] for k in ProfileOut.model_fields if k in row}
    for k in ("industries", "nic_codes", "states", "certifications"):
        data[k] = data.get(k) or []
    data["past_projects"] = row.get("past_projects") or []
    data["turnover_by_year"] = row.get("turnover_by_year") or []
    data["field_sources"] = row.get("field_sources") or {}
    return ProfileOut(**data, extraction_pending=pending)


async def _state(db: AsyncSession, org_id: Any) -> ProfileState:
    confirmed = (
        (
            await db.execute(
                text(
                    "SELECT * FROM company_profiles WHERE org_id = :o AND confirmed_at IS NOT NULL "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"o": org_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    draft = await service.get_draft(db, org_id)
    documents = (
        await db.execute(
            text(
                "SELECT id, kind, filename, uploaded_at, extracted FROM company_documents "
                "WHERE org_id = :o ORDER BY uploaded_at DESC"
            ),
            {"o": org_id},
        )
    ).mappings()
    return ProfileState(
        draft=await _profile_out(db, draft),
        confirmed=await _profile_out(db, dict(confirmed) if confirmed else None),
        documents=[CompanyDocumentOut(**d) for d in documents],
    )


@router.get("/me")
async def me(user: User, db: UserDB) -> Me:
    org = (
        await db.execute(text("SELECT id, name FROM orgs WHERE id = :o"), {"o": user.org_id})
    ).one()
    has = (
        await db.execute(
            text("SELECT 1 FROM company_profiles WHERE org_id = :o AND confirmed_at IS NOT NULL"),
            {"o": user.org_id},
        )
    ).first()
    return Me(
        id=user.id,
        email=user.email,
        role=user.role,
        org=OrgOut(id=org.id, name=org.name),
        has_confirmed_profile=has is not None,
    )


@router.get("/profile")
async def get_profile(user: User, db: UserDB) -> ProfileState:
    return await _state(db, user.org_id)


@router.post("/profile/website")
async def from_website(body: WebsiteRequest, user: User, db: UserDB) -> ProfileState:
    await rate_limit(f"profile_website:{user.org_id}", limit=5, window_s=3600)
    await service.start_from_website(db, user.org_id, str(body.url))
    return await _state(db, user.org_id)


@router.post("/profile/udyam")
async def from_udyam(user: User, db: UserDB, file: Annotated[UploadFile, File()]) -> UdyamOut:
    await rate_limit(f"profile_udyam:{user.org_id}", limit=10, window_s=3600)
    data = await file.read(MAX_UDYAM_BYTES + 1)
    if len(data) > MAX_UDYAM_BYTES or not data.startswith(b"%PDF-"):
        raise HTTPException(422, "upload the Udyam certificate as a PDF (max 10 MB)")
    try:
        details = await service.apply_udyam(db, get_storage(), user.org_id, data)
    except NotUdyamCertificate as exc:
        raise HTTPException(422, "this doesn't look like a Udyam registration certificate") from exc
    return UdyamOut(
        udyam_number=details.udyam_number,
        msme_category=details.msme_category,
        nic_codes=details.nic_codes,
        states=details.states,
    )


@router.post("/profile/ca-certificate")
async def from_ca_certificate(
    user: User, db: UserDB, file: Annotated[UploadFile, File()]
) -> ProfileState:
    """Upload a CA turnover certificate; its year-by-year figures are read in the background
    into the profile draft for review."""
    await rate_limit(f"profile_ca:{user.org_id}", limit=10, window_s=3600)
    data = await file.read(service.MAX_DOC_BYTES + 1)
    try:
        await service.add_ca_certificate(
            db, get_storage(), user.org_id, file.filename or "ca-certificate.pdf", data
        )
    except service.ProfileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _state(db, user.org_id)


@router.patch("/profile")
async def update_profile(body: ProfileUpdate, user: User, db: UserDB) -> ProfileState:
    changes = body.model_dump(exclude_unset=True)
    name = changes.pop("company_name", None)
    if name:
        await db.execute(
            text("UPDATE orgs SET name = :n WHERE id = :o"), {"n": name.strip(), "o": user.org_id}
        )
    for key in ("past_projects", "turnover_by_year"):
        if changes.get(key) is not None:
            changes[key] = [dict(p) for p in changes[key]]
    try:
        await service.update_draft(db, user.org_id, changes)
    except service.ProfileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _state(db, user.org_id)


@router.post("/profile/confirm")
async def confirm_profile(user: User, db: UserDB) -> ProfileState:
    try:
        await service.confirm(db, user.org_id)
    except service.ProfileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _state(db, user.org_id)
