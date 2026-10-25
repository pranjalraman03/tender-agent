"""Draft a company profile from its website: SSRF-safe fetch of a few same-site pages,
text extraction, then one fast-model call. Every extracted field carries its source page and
a quote, so the user can check it before confirming."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import structlog
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser

from core.config import get_settings
from core.llm.claude import (
    UNTRUSTED_NOTE,
    CallContext,
    Claude,
    Usage,
    strict_schema,
    wrap_untrusted,
)
from core.net.safe_fetch import FetchError, UnsafeURL, safe_get
from core.reference.states import STATES

log = structlog.get_logger()

PROMPT_VERSION = "website_profile_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
LINK_HINTS = (
    "about",
    "company",
    "profile",
    "who-we-are",
    "service",
    "product",
    "solution",
    "project",
    "client",
    "portfolio",
    "certif",
    "quality",
    "infrastructure",
    "capabilit",
    "contact",
)
MAX_CHARS_PER_PAGE = 6000


@dataclass(frozen=True)
class Page:
    url: str
    text: str


class Source(BaseModel):
    field: str
    url: str
    quote: str = Field(description="Short exact quote from the page supporting the value")


class PastProject(BaseModel):
    title: str
    client: str | None
    value_inr: float | None
    year: int | None


class WebsiteProfile(BaseModel):
    company_name: str | None
    description: str | None
    industries: list[str]
    states: list[str]
    certifications: list[str]
    past_projects: list[PastProject]
    years_in_business: int | None
    annual_turnover_inr: float | None
    sources: list[Source]


def page_text(html: str) -> tuple[str, list[str]]:
    tree = LexborHTMLParser(html)
    for node in tree.css("script, style, noscript, svg, iframe"):
        node.decompose()
    links = [a.attributes.get("href") or "" for a in tree.css("a[href]")]
    body = tree.body.text(separator="\n", strip=True) if tree.body else ""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return "\n".join(lines), links


def _bare_host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _same_site(base: str, url: str) -> bool:
    return _bare_host(base) == _bare_host(url)


async def fetch_site(url: str) -> list[Page]:
    """Homepage plus up to FETCH_MAX_PAGES-1 same-site pages whose links look relevant."""
    if not urlsplit(url).scheme:
        url = "https://" + url
    max_pages = get_settings().fetch_max_pages
    home = await safe_get(url)
    if not home.content_type.startswith("text/html"):
        raise FetchError("homepage is not HTML")
    text, links = page_text(home.body.decode("utf-8", errors="replace"))
    pages = [Page(home.url, text)]
    candidates: list[str] = []
    for href in links:
        full = urljoin(home.url, href).split("#")[0]
        if full in candidates or full == home.url or not _same_site(home.url, full):
            continue
        if any(h in full.lower() for h in LINK_HINTS):
            candidates.append(full)
    for link in candidates[: max_pages - 1]:
        try:
            result = await safe_get(link)
        except (FetchError, UnsafeURL) as exc:
            log.info("profile_page_skipped", url=link, error=str(exc))
            continue
        if result.status == 200 and result.content_type.startswith("text/html"):
            pages.append(Page(result.url, page_text(result.body.decode("utf-8", "replace"))[0]))
    return pages


async def extract_from_pages(
    claude: Claude, pages: list[Page], allowed_industries: list[str], ctx: CallContext
) -> tuple[WebsiteProfile, Usage]:
    content = "\n\n".join(wrap_untrusted(p.url, p.text[:MAX_CHARS_PER_PAGE]) for p in pages)
    schema = strict_schema(WebsiteProfile)
    schema["properties"]["industries"]["items"] = {"type": "string", "enum": allowed_industries}
    schema["properties"]["states"]["items"] = {"type": "string", "enum": STATES}
    response, usage = await claude.create(
        ctx,
        tier="fast",
        system=PROMPT + "\n\n" + UNTRUSTED_NOTE,
        messages=[
            {
                "role": "user",
                "content": f"Allowed industry slugs: {', '.join(allowed_industries)}\n\n{content}",
            }
        ],
        max_tokens=8000,
        effort="low",
        output_schema=schema,
    )
    raw = "".join(b.text for b in response.content if b.type == "text")
    profile = WebsiteProfile.model_validate_json(raw)
    profile.industries = [i for i in profile.industries if i in allowed_industries]
    profile.states = [s for s in profile.states if s in STATES]
    fetched = {p.url for p in pages}
    profile.sources = [s for s in profile.sources if s.url in fetched]
    return profile, usage


def field_sources(profile: WebsiteProfile) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for s in profile.sources:
        out.setdefault(s.field, []).append({"source": "website", "url": s.url, "quote": s.quote})
    return out
