"""digest_org job: email every user of one org their new good/possible matches on live
tenders, then mark those matches notified. Users only ever see live tenders (rule 1)."""

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.email import send_email
from core.matching.digest import render_digest

log = structlog.get_logger()
MAX_ITEMS = 20


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    org_id = uuid.UUID(str(payload["org_id"]))
    items = [
        dict(r)
        for r in (
            await session.execute(
                text("""
        SELECT t.id AS tender_id, t.title, t.org_name, t.work_state, t.closes_at, m.fit
        FROM matches m JOIN live_tenders t ON t.id = m.tender_id
        WHERE m.org_id = :o AND m.fit IN ('good', 'possible') AND m.notified_at IS NULL
          AND m.user_state IS DISTINCT FROM 'dismissed'
        ORDER BY (m.fit = 'good') DESC, m.score DESC NULLS LAST
        LIMIT :n
    """),
                {"o": org_id, "n": MAX_ITEMS},
            )
        ).mappings()
    ]
    if not items:
        return
    company = (
        await session.execute(text("SELECT name FROM orgs WHERE id = :o"), {"o": org_id})
    ).scalar_one()
    users = (
        (await session.execute(text("SELECT email FROM users WHERE org_id = :o"), {"o": org_id}))
        .scalars()
        .all()
    )
    subject, html_body, text_body = render_digest(company, items)
    for email in users:
        await send_email(email, subject, html_body, text_body)
    await session.execute(
        text("UPDATE matches SET notified_at = now() WHERE org_id = :o AND tender_id = ANY(:t)"),
        {"o": org_id, "t": [i["tender_id"] for i in items]},
    )
    log.info("digest_sent", org_id=str(org_id), users=len(users), items=len(items))
