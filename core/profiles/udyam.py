"""Udyam registration certificate parsing (deterministic; no LLM).

The certificate (udyamregistration.gov.in) lists the registration number, enterprise type per
financial year, major activity, NIC codes, date of incorporation and the plant / office
address. Text comes from the same PDF extractor as tenders (with OCR for scans)."""

import re
from dataclasses import dataclass, field
from datetime import date

from core.parsing.pdf import extract_pdf
from core.reference.states import STATES

UDYAM_NO = re.compile(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}")
CATEGORY_BY_YEAR = re.compile(r"(20\d{2})\s*-\s*\d{2,4}\s*(MICRO|SMALL|MEDIUM)", re.I)
CATEGORY = re.compile(r"Type of Enterprise[^A-Za-z]{0,40}(MICRO|SMALL|MEDIUM)", re.I)
NIC5 = re.compile(r"\b(\d{5})\s*-\s*[A-Za-z]")
NIC4 = re.compile(r"\b(\d{4})\s*-\s*[A-Za-z]")
DATE = r"(\d{2})[/-](\d{2})[/-](\d{4})"
INCORPORATION = re.compile(rf"(?:Incorporation|Commencement)[^\n]{{0,80}}?{DATE}", re.I)
ACTIVITY = re.compile(r"Major Activity[^A-Za-z]{0,20}(Manufacturing|Services|Trading)", re.I)


class NotUdyamCertificate(Exception):
    pass


@dataclass
class UdyamDetails:
    udyam_number: str
    msme_category: str | None
    nic_codes: list[str] = field(default_factory=list)
    major_activity: str | None = None
    incorporated_on: date | None = None
    states: list[str] = field(default_factory=list)

    def years_in_business(self, today: date) -> int | None:
        if self.incorporated_on is None:
            return None
        years = today.year - self.incorporated_on.year
        if (today.month, today.day) < (self.incorporated_on.month, self.incorporated_on.day):
            years -= 1
        return max(years, 0)


def parse_udyam_text(text: str) -> UdyamDetails:
    number = UDYAM_NO.search(text.upper())
    if not number:
        raise NotUdyamCertificate("no Udyam registration number found")
    by_year = CATEGORY_BY_YEAR.findall(text)
    if by_year:  # the latest financial year's classification applies
        category: str | None = max(by_year, key=lambda m: int(m[0]))[1].lower()
    else:
        m = CATEGORY.search(text)
        category = m.group(1).lower() if m else None
    nic5 = list(dict.fromkeys(NIC5.findall(text)))
    nic = nic5 or list(dict.fromkeys(NIC4.findall(text)))
    inc = INCORPORATION.search(text)
    incorporated = None
    if inc:
        d, mth, y = (int(x) for x in inc.groups())
        try:
            incorporated = date(y, mth, d)
        except ValueError:
            incorporated = None
    upper = text.upper()
    states = [s for s in STATES if re.search(rf"\b{re.escape(s.upper())}\b", upper)]
    activity = ACTIVITY.search(text)
    return UdyamDetails(
        udyam_number=number.group(0),
        msme_category=category,
        nic_codes=nic,
        major_activity=activity.group(1).capitalize() if activity else None,
        incorporated_on=incorporated,
        states=states,
    )


async def parse_udyam_pdf(data: bytes) -> UdyamDetails:
    extracted = await extract_pdf(data)
    return parse_udyam_text("\n".join(p.text for p in extracted.pages))
