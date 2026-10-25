"""Email via Resend. Without RESEND_API_KEY (local development), messages are written to
var/outbox/ as .html files and logged instead of sent."""

import asyncio
import html
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from core.config import get_settings

log = structlog.get_logger()
OUTBOX = Path("var/outbox")
RESEND_URL = "https://api.resend.com/emails"


async def send_email(to: str, subject: str, html_body: str, text_body: str) -> str:
    """Returns the provider message id (or the outbox file path locally)."""
    s = get_settings()
    key = s.resend_api_key.get_secret_value()
    if not key:
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", to)
        path = OUTBOX / f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}_{safe}.html"
        content = f"<!-- To: {html.escape(to)} | Subject: {html.escape(subject)} -->\n"
        await asyncio.to_thread(OUTBOX.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, content + html_body)
        log.info("email_written_to_outbox", to=to, subject=subject, path=str(path))
        return str(path)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "from": s.email_from,
                "to": [to],
                "subject": subject,
                "html": html_body,
                "text": text_body,
            },
        )
        response.raise_for_status()
        message_id = str(response.json().get("id", ""))
    log.info("email_sent", to=to, subject=subject, id=message_id)
    return message_id
