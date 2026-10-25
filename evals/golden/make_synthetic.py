"""Builds the synthetic smoke-test PDFs in evals/golden/pdfs/synthetic/.

These are written to look like CPWD-style notices so the pipeline is exercised end to end,
but they are not real tenders. Real golden cases come from evals/label_tool.py.

    uv run python evals/golden/make_synthetic.py
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).parent / "pdfs" / "synthetic"

STREETLIGHT = [
    """DELHI DEVELOPMENT AUTHORITY
NOTICE INVITING E-TENDER
NIT No. 99/EE(E)/SYN/2026-27
1. Name of work: Annual maintenance of street lights and high mast lights in Sector 5 to
Sector 12, Dwarka, New Delhi.
2. Estimated cost put to tender: Rs. 48,50,000/-
3. Earnest money: Rs. 97,000/-
4. Period of completion: 12 months.
SECTION 2 - ELIGIBILITY CRITERIA
1. The bidder should be registered with CPWD, MES, State PWD or any Central PSU in
appropriate class for electrical works.
2. Average annual financial turnover during the last three financial years ending 31st March
2026 should be at least Rs. 14.55 lakh.
3. Experience of having successfully completed similar works during the last seven years:
(a) three similar works each of value not less than Rs. 19.40 lakh; or
(b) two similar works each of value not less than Rs. 24.25 lakh; or
(c) one similar work of value not less than Rs. 38.80 lakh.
Similar work means maintenance of street lighting or outdoor lighting installations.""",
    """4. The bidder must hold a valid electrical contractor licence issued by the Government of
NCT of Delhi.
SECTION 3 - EXEMPTIONS
1. Micro and Small Enterprises registered with Udyam for the tendered item are exempted from
submission of earnest money deposit, as per the Public Procurement Policy for MSEs.
2. No relaxation of turnover or experience is admissible.""",
]

SUPPLY = [
    """ALL INDIA INSTITUTE OF MEDICAL SCIENCES
TENDER ENQUIRY No. SYN/AIIMS/2026/042
1. Item: Supply and installation of 18 units of coaxial indirect ophthalmoscope.
2. Bid security (EMD): Rs. 1,86,480/-
QUALIFICATION CRITERIA
1. The bidder shall be the manufacturer or its authorised distributor.
2. The average annual turnover of the bidder in the last three years should not be less than
Rs. 1.5 crore.
3. The bidder must have supplied similar equipment to at least two Government hospitals in
the last five years.
4. The bidder must have ISO 13485 certification for medical devices.
5. Start-ups and Micro and Small Enterprises are exempted from the prior turnover and prior
experience criteria, subject to meeting quality and technical specifications.""",
]


def write(name: str, pages: list[str]) -> None:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), body, fontsize=10)
    OUT.mkdir(parents=True, exist_ok=True)
    doc.save(OUT / name)
    doc.close()


if __name__ == "__main__":
    write("dda_streetlights.pdf", STREETLIGHT)
    write("aiims_ophthalmoscope.pdf", SUPPLY)
