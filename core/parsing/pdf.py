"""PDF -> per-page text. Tables are rendered as Markdown in reading order; pages with almost
no extractable text are OCR'd (OCRmyPDF + Tesseract, run as a subprocess)."""

import asyncio
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import structlog

log = structlog.get_logger()

# A page with less extractable text than this (and at least one image) is treated as scanned.
SCANNED_PAGE_MIN_CHARS = 40
OCR_TIMEOUT_S = 900


@dataclass(frozen=True)
class PageText:
    page_no: int  # 1-indexed
    text: str


@dataclass(frozen=True)
class ExtractedPdf:
    pages: list[PageText]
    page_count: int
    is_scanned: bool


class PdfError(Exception):
    pass


def _inside(
    block: tuple[float, float, float, float], box: tuple[float, float, float, float]
) -> bool:
    x0, y0, x1, y1 = block
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _page_text(page: pymupdf.Page) -> str:
    """Text blocks in reading order, with tables replaced by their Markdown rendering."""
    try:
        tables = list(page.find_tables().tables)
    except Exception:  # table detection is best-effort; never lose the page text over it
        tables = []
    boxes = [tuple(t.bbox) for t in tables]
    items: list[tuple[float, float, str]] = []
    for x0, y0, x1, y1, text, _no, block_type in page.get_text("blocks", sort=True):
        if block_type != 0 or not text.strip():
            continue
        if any(_inside((x0, y0, x1, y1), box) for box in boxes):
            continue
        items.append((y0, x0, text.strip()))
    for table, box in zip(tables, boxes, strict=True):
        markdown = table.to_markdown().strip()
        if markdown:
            items.append((box[1], box[0], markdown))
    items.sort(key=lambda i: (round(i[0], 1), i[1]))
    return "\n".join(text for *_, text in items)


def _needs_ocr(page: pymupdf.Page, text: str) -> bool:
    return len(text.strip()) < SCANNED_PAGE_MIN_CHARS and bool(page.get_images())


def extract_text(data: bytes) -> tuple[list[PageText], list[int]]:
    """Return per-page text and the 1-indexed page numbers that look scanned."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfError(f"cannot open PDF: {exc}") from exc
    with doc:
        if doc.needs_pass:
            raise PdfError("PDF is password-protected")
        pages: list[PageText] = []
        scanned: list[int] = []
        for i in range(doc.page_count):
            page = doc[i]
            i += 1
            text = _page_text(page)
            pages.append(PageText(i, text))
            if _needs_ocr(page, text):
                scanned.append(i)
    return pages, scanned


async def ocr_pdf(data: bytes) -> bytes:
    """OCR pages that have no text layer; pages with text are left untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.pdf", Path(tmp) / "out.pdf"
        src.write_bytes(data)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "ocrmypdf",
            "--skip-text",
            "-l",
            "eng",
            "--quiet",
            str(src),
            str(dst),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=OCR_TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            raise PdfError("OCR timed out") from None
        # Exit code 6 = "already has text"; nothing to do.
        if proc.returncode == 6:
            return data
        if proc.returncode != 0:
            raise PdfError(f"OCR failed ({proc.returncode}): {stderr.decode()[-500:]}")
        return dst.read_bytes()


async def extract_pdf(data: bytes) -> ExtractedPdf:
    pages, scanned = await asyncio.to_thread(extract_text, data)
    if scanned:
        log.info("ocr_start", scanned_pages=len(scanned), pages=len(pages))
        ocr_pages, _ = await asyncio.to_thread(extract_text, await ocr_pdf(data))
        by_no = {p.page_no: p for p in ocr_pages}
        pages = [by_no.get(p.page_no, p) if p.page_no in scanned else p for p in pages]
    return ExtractedPdf(pages=pages, page_count=len(pages), is_scanned=bool(scanned))
