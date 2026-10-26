"""extract_financials job: read a CA turnover certificate and merge its per-year figures
into the profile draft (verified rows only; the user reviews before confirming)."""

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.claude import CallContext, Claude
from core.parsing.pdf import extract_pdf
from core.profiles.financials import (
    dumps,
    extract_certificate,
    latest_turnover,
    merge_turnover,
    verify_rows,
)
from core.profiles.service import get_or_create_draft
from core.storage import get_storage

log = structlog.get_logger()


def get_claude() -> Claude:  # replaced in tests
    return Claude()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    org_id = uuid.UUID(str(payload["org_id"]))
    document_id = int(payload["document_id"])
    doc = (
        await session.execute(
            text(
                "SELECT id, storage_key FROM company_documents WHERE id = :d AND org_id = :o "
                "AND kind = 'ca_turnover_certificate'"
            ),
            {"d": document_id, "o": org_id},
        )
    ).one_or_none()
    if doc is None:
        log.info("extract_financials_skipped_missing_document", document_id=document_id)
        return

    extracted_pdf = await extract_pdf(await get_storage().get(doc.storage_key))
    document_text = "\n".join(p.text for p in extracted_pdf.pages)
    extraction, _ = await extract_certificate(
        get_claude(),
        document_text,
        CallContext(
            purpose="extract_financials", org_id=org_id, trace_id=f"financials:{document_id}"
        ),
    )
    rows, rejected = (
        verify_rows(extraction, document_text)
        if extraction.is_turnover_certificate
        else ([], ["not a CA turnover certificate"])
    )

    summary = {
        "is_turnover_certificate": extraction.is_turnover_certificate,
        "issued_by": extraction.issued_by,
        "certificate_date": extraction.certificate_date,
        "years": [r["financial_year"] for r in rows],
        "rejected": rejected,
    }
    await session.execute(
        text("UPDATE company_documents SET extracted = CAST(:x AS jsonb) WHERE id = :d"),
        {"x": json.dumps(summary), "d": document_id},
    )

    # The draft the upload was queued for may have been confirmed meanwhile; then the figures
    # go into a new draft so confirmed versions are never edited.
    draft = await get_or_create_draft(session, org_id)
    if rows:
        source = {
            "source": "ca_certificate",
            "document_id": document_id,
            "issued_by": extraction.issued_by,
        }
        merged = merge_turnover(draft.get("turnover_by_year"), rows, source)
        sources = dict(draft.get("field_sources") or {})
        sources["turnover_by_year"] = [source]
        await session.execute(
            text("""
                UPDATE company_profiles
                SET turnover_by_year = CAST(:t AS jsonb), annual_turnover_inr = :latest,
                    field_sources = CAST(:s AS jsonb)
                WHERE id = :id
            """),
            {
                "t": dumps(merged),
                "latest": latest_turnover(merged),
                "s": json.dumps(sources),
                "id": draft["id"],
            },
        )
    log.info(
        "extract_financials_done",
        document_id=document_id,
        years=summary["years"],
        rejected=len(rejected),
    )
