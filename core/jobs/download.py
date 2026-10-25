"""download job: fetch a tender's documents if its portal allows it.

CPPP (the only portal so far) serves documents only behind a captcha, which we never bypass
(CLAUDE.md rule 11). For such portals this job does nothing: the tender stays `discovered`
and appears in the admin "documents needed" queue, where a person downloads the files from
the portal by hand and uploads them (core/documents.py does the rest).
"""

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Portals whose crawler implements fetch_documents(). None yet.
PORTALS_WITH_DOCUMENT_ACCESS: set[str] = set()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    tender_id = int(payload["tender_id"])
    row = (
        await session.execute(
            text("""
                SELECT p.name AS portal, t.lifecycle_status, t.closes_at > now() AS open
                FROM tenders t JOIN portals p ON p.id = t.portal_id WHERE t.id = :id
            """),
            {"id": tender_id},
        )
    ).one_or_none()
    if row is None or row.lifecycle_status not in ("open", "extended") or not row.open:
        log.info("download_skipped_not_live", tender_id=tender_id)
        return
    if row.portal not in PORTALS_WITH_DOCUMENT_ACCESS:
        log.info("download_needs_manual_upload", tender_id=tender_id, portal=row.portal)
        return
    raise NotImplementedError(f"document download for {row.portal}")
