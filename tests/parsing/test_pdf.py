import shutil

import pytest

from core.parsing.pdf import PdfError, extract_pdf
from tests.parsing.samples import TENDER_PAGES, scanned_pdf, text_pdf


async def test_extract_text_pdf() -> None:
    result = await extract_pdf(text_pdf(TENDER_PAGES))
    assert result.page_count == 3 and not result.is_scanned
    assert "Average annual financial turnover" in result.pages[0].text
    assert "exempted from EMD" in result.pages[1].text


async def test_rejects_garbage() -> None:
    with pytest.raises(PdfError):
        await extract_pdf(b"%PDF-1.4 not really a pdf")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
async def test_scanned_pdf_is_ocrd() -> None:
    result = await extract_pdf(scanned_pdf("Minimum average annual turnover Rs 50 lakh"))
    assert result.is_scanned
    assert "turnover" in result.pages[0].text.lower()
