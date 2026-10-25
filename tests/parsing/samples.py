"""Helpers that build small PDFs for tests."""

import pymupdf

TENDER_PAGES = [
    """NOTICE INVITING TENDER
Tender No. 55/EE(E)/ELD-12/DDA/2026-27
Page 1 of 3
1. Name of work: Annual maintenance of street lights in Dwarka.
2. Estimated cost: Rs. 27,69,088/-
SECTION 3 - ELIGIBILITY CRITERIA
1. The bidder must be registered with CPWD or equivalent.
1.1 Average annual financial turnover during the last 3 years shall be at least
Rs. 8.30 lakh.
10.50 lakh is the value of a similar completed work referred to in clause 1.2.
1.2 Experience of having completed similar works during the last 7 years:
(a) three similar works each of value not less than Rs. 11.07 lakh; or
(b) two similar works each of value not less than Rs. 13.84 lakh; or
(c) one similar work of value not less than Rs. 22.15 lakh.""",
    """Page 2 of 3
2. Micro and Small Enterprises registered with NSIC or Udyam are exempted from EMD
as per the Public Procurement Policy for MSEs.
3. Earnest money of Rs. 55,382 shall be paid online.""",
    """Page 3 of 3
ANNEXURE A
The bidder shall submit the following documents.
Copy of PAN card. Copy of GST registration.""",
]


def text_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def scanned_pdf(text: str) -> bytes:
    """A PDF whose only page is an image of text (no text layer)."""
    src = pymupdf.open()
    page = src.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=14)
    pix = page.get_pixmap(dpi=200)
    src.close()
    doc = pymupdf.open()
    img_page = doc.new_page()
    img_page.insert_image(img_page.rect, pixmap=pix)
    data: bytes = doc.tobytes()
    doc.close()
    return data
