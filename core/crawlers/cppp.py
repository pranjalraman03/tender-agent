"""CPPP (eprocure.gov.in) crawler.

Access check (2026-10-24): no robots.txt. The homepage "Latest Tenders" table and tender
detail pages are public. The full active-tenders listing and document downloads are behind
a captcha, so this crawler only reads the homepage and detail pages, and never downloads
documents. Detail links are tied to the server session, so one httpx client (cookie jar)
is used for a whole run.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from selectolax.lexbor import LexborHTMLParser

from core.crawlers.base import (
    CorrigendumNotice,
    CrawlError,
    ListingItem,
    RateLimiter,
    TenderDetail,
)

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://eprocure.gov.in"
HOME_PATH = "/eprocure/app"
DATE_FORMAT = "%d-%b-%Y %I:%M %p"  # e.g. 08-Dec-2026 05:00 PM


def parse_ist(value: str) -> datetime | None:
    """Portal dates are Indian time; return an aware datetime (CLAUDE.md rule 5)."""
    value = value.strip()
    if not value or value.upper() == "NA":
        return None
    return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=IST)


def parse_inr(value: str) -> Decimal | None:
    """'1,49,57,00,000' -> Decimal('1495700000'). 'NA' or empty -> None."""
    cleaned = value.replace(",", "").replace("₹", "").strip()
    if not cleaned or cleaned.upper() == "NA":
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_listing(html: str) -> list[ListingItem]:
    tree = LexborHTMLParser(html)
    items: list[ListingItem] = []
    for row in tree.css("table#activeTenders tr"):
        cells = row.css("td")
        link = row.css_first("a")
        if len(cells) < 3 or link is None:
            continue
        href = link.attributes.get("href")
        if not href:
            continue
        title = re.sub(r"^\d+\.\s*", "", link.text(strip=True))
        items.append(
            ListingItem(
                title=title,
                reference_no=cells[1].text(strip=True),
                closes_at=parse_ist(cells[2].text(strip=True)),
                detail_url=BASE_URL + href,
            )
        )
    return items


def parse_corrigenda(html: str) -> list[CorrigendumNotice]:
    """The homepage 'Latest Corrigendum' table: title, reference no, new closing date."""
    tree = LexborHTMLParser(html)
    out: list[CorrigendumNotice] = []
    for row in tree.css("table#activeCorrigendums tr"):
        cells = row.css("td")
        if len(cells) < 3:
            continue
        out.append(
            CorrigendumNotice(
                title=re.sub(r"^\d+\.\s*", "", cells[0].text(strip=True)),
                reference_no=cells[1].text(strip=True),
                closes_at=parse_ist(cells[2].text(strip=True)),
            )
        )
    return out


def parse_detail(html: str) -> TenderDetail:
    tree = LexborHTMLParser(html)
    if "Stale Session" in html[:3000]:
        raise CrawlError("stale session: detail link expired")
    fields: dict[str, str] = {}
    for caption in tree.css("td.td_caption"):
        label = caption.text(strip=True)
        value_cell = caption.next
        while value_cell is not None and value_cell.tag != "td":
            value_cell = value_cell.next
        if label and value_cell is not None and label not in fields:
            fields[label] = value_cell.text(strip=True)

    tender_id = fields.get("Tender ID")
    title = fields.get("Title") or fields.get("Work Description")
    if not tender_id or not title:
        raise CrawlError("detail page missing Tender ID or Title")
    org_chain = fields.get("Organisation Chain", "")
    return TenderDetail(
        tender_ref=tender_id,
        title=title,
        org_name=org_chain.split("||")[0].strip() or None,
        value_inr=parse_inr(fields.get("Tender Value in ₹", "")),
        emd_inr=parse_inr(fields.get("EMD Amount in ₹", "")),
        published_at=parse_ist(fields.get("Published Date", "")),
        closes_at=parse_ist(fields.get("Bid Submission End Date", "")),
        # Detail URLs are session-bound and expire, so link to the portal home instead.
        source_url=BASE_URL + HOME_PATH,
        raw=fields,
    )


class CpppCrawler:
    def __init__(self, client: httpx.AsyncClient, min_interval_s: float = 3.0) -> None:
        self.client = client
        self.limiter = RateLimiter(min_interval_s)

    async def _get(self, url: str) -> str:
        await self.limiter.wait()
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

    async def list_new(self) -> list[ListingItem]:
        return parse_listing(await self._get(BASE_URL + HOME_PATH))

    async def fetch_detail(self, item: ListingItem) -> TenderDetail:
        return parse_detail(await self._get(item.detail_url))

    async def list_corrigenda(self) -> list[CorrigendumNotice]:
        return parse_corrigenda(await self._get(BASE_URL + HOME_PATH))
