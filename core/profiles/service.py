"""Profile lifecycle. Profiles are versioned rows: a draft (confirmed_at IS NULL) is created
from the latest confirmed version, filled from the website / Udyam certificate / user edits,
and confirming it makes it the version matching uses. Reports are cached per version, so a
confirmed version is never edited in place."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.agent.turnover import TurnoverRuleError, fy_label, parse_fy
from core.profiles.financials import latest_turnover
from core.profiles.nic import industries_for_nic
from core.profiles.udyam import UdyamDetails, parse_udyam_pdf
from core.reference.states import STATES
from core.storage import Storage

EDITABLE: dict[str, type] = {
    "website_url": str,
    "description": str,
    "industries": list,
    "nic_codes": list,
    "msme_category": str,
    "states": list,
    "years_in_business": int,
    "incorporated_on": date,
    "is_msme": bool,
    "certifications": list,
    "past_projects": list,
    "turnover_by_year": list,
}
JSON_FIELDS = {"past_projects", "turnover_by_year"}
MAX_DOC_BYTES = 10 * 1024 * 1024


class ProfileError(Exception):
    pass


async def get_draft(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT * FROM company_profiles WHERE org_id = :o AND confirmed_at IS NULL "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"o": org_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


async def get_or_create_draft(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    draft = await get_draft(session, org_id)
    if draft:
        return draft
    # Start from the latest confirmed version (if any) so edits keep what the user had.
    latest = (
        (
            await session.execute(
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
    next_version = (
        await session.execute(
            text("SELECT coalesce(max(version), 0) + 1 FROM company_profiles WHERE org_id = :o"),
            {"o": org_id},
        )
    ).scalar_one()
    base: dict[str, Any] = dict(latest) if latest else {}
    await session.execute(
        text("""
            INSERT INTO company_profiles (
                org_id, version, website_url, description, industries, nic_codes,
                msme_category, states, annual_turnover_inr, years_in_business, is_msme,
                certifications, past_projects, field_sources, turnover_by_year,
                incorporated_on)
            VALUES (:o, :v, :website_url, :description, :industries, :nic_codes,
                    :msme_category, :states, :turnover, :years, :is_msme, :certifications,
                    CAST(:past_projects AS jsonb), CAST(:field_sources AS jsonb),
                    CAST(:turnover_by_year AS jsonb), :incorporated_on)
        """),
        {
            "o": org_id,
            "v": next_version,
            "website_url": base.get("website_url"),
            "description": base.get("description"),
            "industries": base.get("industries") or [],
            "nic_codes": base.get("nic_codes") or [],
            "msme_category": base.get("msme_category"),
            "states": base.get("states") or [],
            "turnover": base.get("annual_turnover_inr"),
            "years": base.get("years_in_business"),
            "is_msme": base.get("is_msme"),
            "certifications": base.get("certifications") or [],
            "past_projects": json.dumps(base.get("past_projects") or []),
            "field_sources": json.dumps(base.get("field_sources") or {}),
            "turnover_by_year": json.dumps(base.get("turnover_by_year") or []),
            "incorporated_on": base.get("incorporated_on"),
        },
    )
    draft = await get_draft(session, org_id)
    assert draft is not None
    return draft


async def start_from_website(session: AsyncSession, org_id: uuid.UUID, url: str) -> int:
    draft = await get_or_create_draft(session, org_id)
    await session.execute(
        text("UPDATE company_profiles SET website_url = :u WHERE id = :id"),
        {"u": url, "id": draft["id"]},
    )
    await queue.enqueue(
        session,
        "extract_profile",
        {"org_id": str(org_id), "profile_id": draft["id"]},
        f"extract_profile:{draft['id']}:{hashlib.sha256(url.encode()).hexdigest()[:12]}",
    )
    return int(draft["id"])


def _merge_sources(existing: dict[str, Any], field: str, source: dict[str, Any]) -> None:
    existing.setdefault(field, [])
    if source not in existing[field]:
        existing[field].append(source)


async def apply_udyam(
    session: AsyncSession, storage: Storage, org_id: uuid.UUID, data: bytes
) -> UdyamDetails:
    details = await parse_udyam_pdf(data)
    await _store_document(session, storage, org_id, "udyam", "udyam.pdf", data)
    draft = await get_or_create_draft(session, org_id)
    sources = dict(draft["field_sources"] or {})
    src = {"source": "udyam", "udyam_number": details.udyam_number}
    industries = list(draft["industries"] or [])
    for slug in await industries_for_nic(session, details.nic_codes):
        if slug not in industries:
            industries.append(slug)
    states = list(dict.fromkeys([*(draft["states"] or []), *details.states]))
    years = details.years_in_business(datetime.now(UTC).date())
    for f in ("msme_category", "nic_codes", "is_msme", "industries", "states"):
        _merge_sources(sources, f, src)
    if years is not None:
        _merge_sources(sources, "years_in_business", src)
    if details.incorporated_on is not None:
        _merge_sources(sources, "incorporated_on", src)
    await session.execute(
        text("""
            UPDATE company_profiles SET
              msme_category = coalesce(:cat, msme_category), nic_codes = :nic, is_msme = true,
              industries = :ind, states = :states,
              years_in_business = coalesce(:years, years_in_business),
              incorporated_on = coalesce(:incorporated, incorporated_on),
              field_sources = CAST(:sources AS jsonb)
            WHERE id = :id
        """),
        {
            "incorporated": details.incorporated_on,
            "cat": details.msme_category,
            "nic": details.nic_codes,
            "ind": industries,
            "states": states,
            "years": years,
            "sources": json.dumps(sources),
            "id": draft["id"],
        },
    )
    return details


async def _store_document(
    session: AsyncSession,
    storage: Storage,
    org_id: uuid.UUID,
    kind: str,
    filename: str,
    data: bytes,
) -> int:
    """Store an uploaded company document (idempotent per org + content). Returns its id."""
    sha = hashlib.sha256(data).hexdigest()
    key = f"orgs/{org_id}/{kind}/{sha}.pdf"
    await storage.put(key, data, "application/pdf")
    doc_id = (
        await session.execute(
            text("""
            INSERT INTO company_documents (org_id, kind, storage_key, sha256, filename)
            VALUES (:o, :kind, :key, :sha, :name)
            ON CONFLICT (org_id, sha256) DO UPDATE SET filename = EXCLUDED.filename
            RETURNING id
        """),
            {"o": org_id, "kind": kind, "key": key, "sha": sha, "name": filename[:255]},
        )
    ).scalar_one()
    return int(doc_id)


async def add_ca_certificate(
    session: AsyncSession, storage: Storage, org_id: uuid.UUID, filename: str, data: bytes
) -> int:
    """Store a CA turnover certificate and queue extraction of its year-by-year figures into
    the profile draft. Returns the document id."""
    if len(data) > MAX_DOC_BYTES or not data.startswith(b"%PDF-"):
        raise ProfileError("upload the CA turnover certificate as a PDF (max 10 MB)")
    doc_id = await _store_document(
        session, storage, org_id, "ca_turnover_certificate", filename, data
    )
    draft = await get_or_create_draft(session, org_id)
    await queue.enqueue(
        session,
        "extract_financials",
        {"org_id": str(org_id), "profile_id": draft["id"], "document_id": doc_id},
        f"extract_financials:{doc_id}:{draft['id']}",
    )
    return doc_id


def _clean_turnover(rows: list[Any]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ProfileError("turnover_by_year rows must be objects")
        try:
            label = fy_label(parse_fy(str(row.get("financial_year", ""))))
            amount = float(row["turnover_inr"])
        except (TurnoverRuleError, KeyError, TypeError, ValueError) as exc:
            raise ProfileError(f"invalid turnover row {row!r}") from exc
        if amount < 0:
            raise ProfileError("turnover can't be negative")
        clean: dict[str, Any] = {"financial_year": label, "turnover_inr": amount}
        if isinstance(row.get("source"), dict):
            clean["source"] = row["source"]
        out[label] = clean
    return [out[k] for k in sorted(out, key=parse_fy, reverse=True)]


def _clean(field: str, value: Any) -> Any:
    kind = EDITABLE[field]
    if value is None:
        return None
    if kind is list:
        if not isinstance(value, list):
            raise ProfileError(f"{field} must be a list")
        if field == "states" and any(s not in STATES for s in value):
            raise ProfileError("unknown state")
        if field == "turnover_by_year":
            return _clean_turnover(value)
        return value
    if kind is date:
        try:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        except ValueError as exc:
            raise ProfileError(f"{field} must be a date (YYYY-MM-DD)") from exc
    if kind is bool:
        return bool(value)
    if kind is int:
        return int(value)
    if kind is float:
        return float(value)
    return str(value).strip() or None


async def update_draft(
    session: AsyncSession, org_id: uuid.UUID, changes: dict[str, Any]
) -> dict[str, Any]:
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise ProfileError(f"cannot edit {sorted(unknown)}")
    draft = await get_or_create_draft(session, org_id)
    if "industries" in changes:
        allowed = set((await session.execute(text("SELECT slug FROM industries"))).scalars())
        if any(i not in allowed for i in changes["industries"] or []):
            raise ProfileError("unknown industry")
    sources = dict(draft["field_sources"] or {})
    params: dict[str, Any] = {"id": draft["id"]}
    sets = []
    for f, v in changes.items():
        value = _clean(f, v)
        if f in JSON_FIELDS:
            sets.append(f"{f} = CAST(:{f} AS jsonb)")
            params[f] = json.dumps(value or [])
        else:
            sets.append(f"{f} = :{f}")
            params[f] = value
        if f == "turnover_by_year":
            # Rows the user typed or changed are marked as theirs; certificate rows keep their
            # source. The latest year also feeds annual_turnover_inr (display / ranking).
            before = {r["financial_year"]: r for r in draft.get("turnover_by_year") or []}
            for row in value:
                old = before.get(row["financial_year"])
                if old is None or old.get("turnover_inr") != row["turnover_inr"]:
                    row["source"] = {"source": "user"}
                elif "source" in old:
                    row["source"] = old["source"]
            params[f] = json.dumps(value)
            sets.append("annual_turnover_inr = :latest_turnover")
            params["latest_turnover"] = latest_turnover(value)
        elif value != draft.get(f):
            sources[f] = [{"source": "user"}]
    if sets:
        params["sources"] = json.dumps(sources)
        await session.execute(
            # Column names come from EDITABLE (checked above); values are bound parameters.
            text(
                f"UPDATE company_profiles SET {', '.join(sets)}, "  # noqa: S608
                "field_sources = CAST(:sources AS jsonb) WHERE id = :id"
            ),
            params,
        )
    updated = await get_draft(session, org_id)
    assert updated is not None
    return updated


async def confirm(session: AsyncSession, org_id: uuid.UUID) -> int:
    """Confirm the draft. Returns the confirmed version and enqueues match_profile."""
    draft = await get_draft(session, org_id)
    if draft is None:
        raise ProfileError("no draft to confirm")
    if not draft["industries"]:
        raise ProfileError("choose at least one industry")
    if not draft["states"]:
        raise ProfileError("choose at least one state")
    await session.execute(
        text(
            "UPDATE company_profiles SET confirmed_at = now(), profile_embedding = NULL "
            "WHERE id = :id"
        ),
        {"id": draft["id"]},
    )
    version = int(draft["version"])
    await queue.enqueue(
        session,
        "match_profile",
        {"org_id": str(org_id), "version": version},
        f"match_profile:{org_id}:v{version}",
    )
    return version
