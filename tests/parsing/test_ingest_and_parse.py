import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.documents import InvalidDocument, extract_pdfs, ingest_document
from core.jobs import parse
from core.storage import LocalStorage
from tests.parsing.samples import TENDER_PAGES, text_pdf

SM = async_sessionmaker[AsyncSession]


@pytest.fixture
async def tender_id(sessionmaker: SM, portal_id: int) -> int:
    async with sessionmaker() as s, s.begin():
        return int(
            (
                await s.execute(
                    text(
                        "INSERT INTO tenders (portal_id, tender_ref, title, closes_at) "
                        "VALUES (:p, 'T1', 'Street lights', now() + interval '10 days') RETURNING id"
                    ),
                    {"p": portal_id},
                )
            ).scalar_one()
        )


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_extract_pdfs_from_zip_skips_non_pdfs() -> None:
    pdf = text_pdf(["hello"])
    pdfs, skipped = extract_pdfs("docs.zip", _zip({"a/nit.pdf": pdf, "boq.xls": b"xls"}))
    assert [n for n, _ in pdfs] == ["nit.pdf"] and skipped == ["boq.xls"]
    with pytest.raises(InvalidDocument):
        extract_pdfs("x.txt", b"plain text")


async def test_ingest_then_parse(
    sessionmaker: SM, tender_id: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(str(tmp_path))
    monkeypatch.setattr(parse, "get_storage", lambda: storage)
    pdf = text_pdf(TENDER_PAGES)

    async with sessionmaker() as s, s.begin():
        first = await ingest_document(s, storage, tender_id, "nit.pdf", pdf)
    async with sessionmaker() as s, s.begin():
        again = await ingest_document(s, storage, tender_id, "copy.zip", _zip({"nit.pdf": pdf}))
    assert len(first.new_document_ids) == 1
    assert again.new_document_ids == [] and again.duplicates == 1

    async with sessionmaker() as s:
        status = (
            await s.execute(
                text("SELECT pipeline_status FROM tenders WHERE id = :t"), {"t": tender_id}
            )
        ).scalar_one()
        jobs = (await s.execute(text("SELECT kind, payload FROM jobs"))).all()
    assert status == "downloaded"
    assert [j.kind for j in jobs] == ["parse"]

    for _ in range(2):  # parse is idempotent
        async with sessionmaker() as s, s.begin():
            await parse.handle(jobs[0].payload, s)

    async with sessionmaker() as s:
        clauses = (
            await s.execute(text("SELECT clause_no, section, page_start FROM clauses ORDER BY id"))
        ).all()
        tender = (await s.execute(text("SELECT pipeline_status FROM tenders"))).scalar_one()
        kinds = (await s.execute(text("SELECT kind FROM jobs ORDER BY id"))).scalars().all()
        doc = (await s.execute(text("SELECT page_count, parsed_at FROM tender_documents"))).one()
    nos = [c.clause_no for c in clauses]
    assert "1.2(b)" in nos and nos.count("1.1") == 1
    assert tender == "parsed" and kinds == ["parse", "index"]
    assert doc.page_count == 3 and doc.parsed_at is not None
