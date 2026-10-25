"""parse job: PDF text (+ OCR fallback, tables) -> clauses. Enqueues `index` once every
document of the tender is parsed."""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.parsing.chunker import chunk_pages
from core.parsing.pdf import extract_pdf
from core.storage import get_storage

log = structlog.get_logger()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    document_id = int(payload["document_id"])
    doc = (
        await session.execute(
            text("""
                SELECT d.id, d.tender_id, d.storage_key, t.lifecycle_status,
                       t.closes_at IS NULL OR t.closes_at > now() AS open
                FROM tender_documents d JOIN tenders t ON t.id = d.tender_id
                WHERE d.id = :id
            """),
            {"id": document_id},
        )
    ).one_or_none()
    if doc is None:
        log.info("parse_skipped_missing_document", document_id=document_id)
        return
    if doc.lifecycle_status not in ("open", "extended") or not doc.open:
        log.info("parse_skipped_not_live", document_id=document_id)
        return

    data = await get_storage().get(doc.storage_key)
    extracted = await extract_pdf(data)
    chunks = chunk_pages(extracted.pages)

    # Idempotent: a re-run replaces this document's clauses.
    await session.execute(text("DELETE FROM clauses WHERE document_id = :id"), {"id": doc.id})
    for c in chunks:
        await session.execute(
            text("""
                INSERT INTO clauses (document_id, tender_id, clause_no, section,
                                     page_start, page_end, text)
                VALUES (:doc, :tender, :no, :section, :p0, :p1, :text)
            """),
            {
                "doc": doc.id,
                "tender": doc.tender_id,
                "no": c.clause_no,
                "section": c.section,
                "p0": c.page_start,
                "p1": c.page_end,
                "text": c.text,
            },
        )
    await session.execute(
        text("""
            UPDATE tender_documents
            SET parsed_at = now(), page_count = :pages, is_scanned = :scanned
            WHERE id = :id
        """),
        {"id": doc.id, "pages": extracted.page_count, "scanned": extracted.is_scanned},
    )

    pending = (
        await session.execute(
            text(
                "SELECT count(*) FROM tender_documents WHERE tender_id = :t AND parsed_at IS NULL"
            ),
            {"t": doc.tender_id},
        )
    ).scalar_one()
    if pending == 0:
        await session.execute(
            text("""
                UPDATE tenders SET pipeline_status = 'parsed', updated_at = now()
                WHERE id = :t AND pipeline_status IN ('downloaded', 'failed')
            """),
            {"t": doc.tender_id},
        )
        # Keyed by document so a corrigendum on an indexed tender triggers a new index run.
        await queue.enqueue(
            session,
            "index",
            {"tender_id": doc.tender_id, "trigger_document_id": doc.id},
            f"index:{doc.tender_id}:{doc.id}",
        )
    log.info(
        "parsed",
        document_id=doc.id,
        pages=extracted.page_count,
        clauses=len(chunks),
        scanned=extracted.is_scanned,
    )
