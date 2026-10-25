"""Crawler protocol shared by all portal crawlers."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ListingItem:
    """One row of a portal's listing page."""

    title: str
    reference_no: str
    closes_at: datetime | None
    detail_url: str


@dataclass(frozen=True)
class TenderDetail:
    tender_ref: str  # portal-unique id
    title: str
    org_name: str | None
    value_inr: Decimal | None
    emd_inr: Decimal | None
    published_at: datetime | None
    closes_at: datetime | None
    source_url: str | None
    raw: dict[str, str] = field(default_factory=dict)  # all caption -> value pairs


@dataclass(frozen=True)
class CorrigendumNotice:
    """A portal's notice that an existing tender was amended."""

    title: str
    reference_no: str
    closes_at: datetime | None


class Crawler(Protocol):
    async def list_new(self) -> list[ListingItem]: ...

    async def fetch_detail(self, item: ListingItem) -> TenderDetail: ...

    async def list_corrigenda(self) -> list[CorrigendumNotice]: ...


class CrawlError(Exception):
    pass


class RateLimiter:
    """Enforces a minimum interval between requests (one crawler, one portal)."""

    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._last = 0.0

    async def wait(self) -> None:
        delay = self._last + self.min_interval_s - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._last = time.monotonic()
