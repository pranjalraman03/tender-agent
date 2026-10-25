"""Bring tender documents into the system: dedup, store in the bucket, record, enqueue parse.

Documents arrive either from a crawler that can download them, or from a person uploading
them (admin "documents needed" queue, or a user on the tender page) when the portal puts
downloads behind a captcha. Both paths call `ingest_document`.
"""

import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.storage import Storage

log = structlog.get_logger()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 50
MAX_ZIP_TOTAL_BYTES = 300 * 1024 * 1024
PDF_MAGIC = b"%PDF-"


class InvalidDocument(Exception):
    pass


@dataclass(frozen=True)
class IngestResult:
    new_document_ids: list[int]
    duplicates: int
    skipped_files: list[str]


def extract_pdfs(filename: str, data: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Return (pdfs, skipped names). A ZIP is unpacked (one level, with size caps)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocument("file too large")
    if data.startswith(PDF_MAGIC):
        return [(filename, data)], []
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise InvalidDocument("not a PDF or ZIP file")

    pdfs: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if len(entries) > MAX_ZIP_ENTRIES:
            raise InvalidDocument("too many files in ZIP")
        for entry in entries:
            total += entry.file_size  # declared size; checked again after reading
            if total > MAX_ZIP_TOTAL_BYTES:
                raise InvalidDocument("ZIP contents too large")
            with archive.open(entry) as f:
                content = f.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise InvalidDocument("file in ZIP too large")
            name = entry.filename.rsplit("/", 1)[-1]
            if content.startswith(PDF_MAGIC):
                pdfs.append((name, content))
            else:
                skipped.append(name)  # e.g. BOQ spreadsheets; not parsed in v1
    return pdfs, skipped


async def ingest_document(
    session: AsyncSession,
    storage: Storage,
    tender_id: int,
    filename: str,
    data: bytes,
    *,
    source: str = "crawler",
    uploaded_by: uuid.UUID | None = None,
) -> IngestResult:
    """Store new PDFs for a tender and enqueue `parse` for each, in the caller's transaction.

    Uploading the same file to the same tender twice is a no-op ((tender_id, sha256) is
    unique); the same file on another tender is stored for that tender too. If the tender
    was already indexed, a new document is treated as a corrigendum: it is parsed and
    re-indexed while the tender stays visible.
    """
    pdfs, skipped = extract_pdfs(filename, data)
    if not pdfs:
        raise InvalidDocument("no PDF files found")

    new_ids: list[int] = []
    duplicates = 0
    for name, content in pdfs:
        sha = hashlib.sha256(content).hexdigest()
        key = f"tenders/{tender_id}/{sha}.pdf"
        exists = (
            await session.execute(
                text("SELECT 1 FROM tender_documents WHERE tender_id = :t AND sha256 = :sha"),
                {"t": tender_id, "sha": sha},
            )
        ).first()
        if exists:
            duplicates += 1
            continue
        # Upload before the row commits. If the transaction later rolls back, the object is
        # orphaned but harmless: the key is content-addressed, so a retry overwrites it.
        await storage.put(key, content, "application/pdf")
        doc_id = (
            await session.execute(
                text("""
                    INSERT INTO tender_documents (tender_id, storage_key, sha256, filename,
                                                  source, uploaded_by)
                    VALUES (:tender_id, :key, :sha, :name, :source, :by)
                    ON CONFLICT (tender_id, sha256) DO NOTHING
                    RETURNING id
                """),
                {
                    "tender_id": tender_id,
                    "key": key,
                    "sha": sha,
                    "name": name[:255],
                    "source": source,
                    "by": uploaded_by,
                },
            )
        ).scalar_one_or_none()
        if doc_id is None:
            duplicates += 1
            continue
        new_ids.append(doc_id)
        await queue.enqueue(
            session, "parse", {"tender_id": tender_id, "document_id": doc_id}, f"parse:{doc_id}"
        )

    if new_ids:
        await session.execute(
            text("""
                UPDATE tenders SET pipeline_status = 'downloaded', updated_at = now()
                WHERE id = :id AND pipeline_status IN ('discovered', 'failed')
            """),
            {"id": tender_id},
        )
    log.info(
        "documents_ingested",
        tender_id=tender_id,
        new=len(new_ids),
        duplicates=duplicates,
        skipped=len(skipped),
    )
    return IngestResult(new_ids, duplicates, skipped)
