"""Daily digest: new good / possible matches on live tenders, one email per user."""

from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from core.config import get_settings

IST = ZoneInfo("Asia/Kolkata")
FIT_LABEL = {"good": "Good fit", "possible": "Possible fit"}


def render_digest(company: str, items: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Returns (subject, html, text)."""
    base = get_settings().web_base_url.rstrip("/")
    subject = f"{len(items)} new tender{'s' if len(items) != 1 else ''} for {company}"
    rows_html, rows_text = [], []
    for it in items:
        closes = it["closes_at"].astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
        url = f"{base}/tenders/{it['tender_id']}"
        label = FIT_LABEL.get(it["fit"] or "", "Shortlisted")
        rows_html.append(
            f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee'>"
            f"<a href='{escape(url)}' style='color:#0b57d0;font-weight:600'>"
            f"{escape(it['title'])}</a>"
            f"<br><span style='color:#555'>{escape(it['org_name'] or '')} · "
            f"{escape(it['work_state'] or 'All India')} · closes {escape(closes)}</span>"
            f"<br><span style='color:#137333'>{escape(label)}</span></td></tr>"
        )
        rows_text.append(f"- {it['title']} ({label}), closes {closes}\n  {url}")
    html_body = (
        "<div style='font-family:system-ui,sans-serif;max-width:640px'>"
        f"<h2 style='font-weight:600'>New tenders for {escape(company)}</h2>"
        f"<table style='width:100%;border-collapse:collapse'>{''.join(rows_html)}</table>"
        f"<p style='color:#777;font-size:13px'>Eligibility is assessed from the tender "
        f"documents; always check the cited clauses before bidding. "
        f"<a href='{escape(base)}/matches'>See all matches</a></p></div>"
    )
    text_body = f"New tenders for {company}\n\n" + "\n".join(rows_text) + f"\n\n{base}/matches"
    return subject, html_body, text_body
