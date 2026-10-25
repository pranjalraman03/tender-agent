"""index job: embed clauses, extract fields + industries, embed scope, mark `indexed`,
record a `published` (or `corrigendum`) event, enqueue match_tender / fit_check rechecks."""

import json
from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import queue
from core.indexing.fields import extract_fields, to_decimal
from core.llm.claude import CallContext, Claude
from core.llm.embeddings import embed, to_pgvector

log = structlog.get_logger()

ELIGIBILITY_WORDS = ("eligib", "qualif", "turnover", "experience", "criteria", "msme", "mse")


def get_claude() -> Claude:  # replaced in tests
    return Claude()


async def handle(payload: dict[str, Any], session: AsyncSession) -> None:
    tender_id = int(payload["tender_id"])
    trigger_doc = payload.get("trigger_document_id")
    tender = (
        await session.execute(
            text("""
                SELECT id, title, org_name, portal_fields, work_state, pipeline_status,
                       lifecycle_status, closes_at IS NULL OR closes_at > now() AS open
                FROM tenders WHERE id = :id
            """),
            {"id": tender_id},
        )
    ).one_or_none()
    if tender is None or tender.lifecycle_status not in ("open", "extended") or not tender.open:
        log.info("index_skipped_not_live", tender_id=tender_id)
        return
    was_indexed = tender.pipeline_status == "indexed"

    clauses = (
        await session.execute(
            text("""
                SELECT c.id, c.clause_no, c.section, c.page_start, c.text, c.document_id,
                       c.embedding IS NULL AS needs_embedding
                FROM clauses c WHERE c.tender_id = :id ORDER BY c.document_id, c.id
            """),
            {"id": tender_id},
        )
    ).all()
    if not clauses:
        raise ValueError(f"tender {tender_id} has no clauses to index")

    # 1. Clause embeddings (only missing ones; re-runs are cheap).
    todo = [c for c in clauses if c.needs_embedding]
    vectors = await embed([f"{c.section or ''}\n{c.text}" for c in todo], "document")
    for c, v in zip(todo, vectors, strict=True):
        await session.execute(
            text("UPDATE clauses SET embedding = CAST(:v AS vector) WHERE id = :id"),
            {"v": to_pgvector(v), "id": c.id},
        )

    # 2. Fields + industries (fast model, JSON schema, labels limited to the industries table).
    allowed = list(
        (await session.execute(text("SELECT slug FROM industries ORDER BY slug"))).scalars()
    )
    fields, _ = await extract_fields(
        get_claude(),
        tender,
        list(clauses),
        allowed,
        CallContext(purpose="extract_fields", trace_id=f"index:{tender_id}"),
    )

    # 3. Scope embedding for the matching funnel.
    scope_text = f"{tender.title}\n{fields.summary}\nIndustries: {', '.join(fields.industries)}"
    (scope_vec,) = await embed([scope_text], "document")

    await session.execute(
        text("""
            UPDATE tenders SET
              industries = :industries,
              work_state = coalesce(work_state, :state),
              is_central = :central,
              value_inr = coalesce(value_inr, :value),
              emd_inr = coalesce(emd_inr, :emd),
              summary = :summary,
              scope_embedding = CAST(:scope AS vector),
              pipeline_status = 'indexed',
              updated_at = now()
            WHERE id = :id
        """),
        {
            "id": tender_id,
            "industries": fields.industries,
            "state": fields.work_state,
            "central": fields.is_central,
            "value": to_decimal(fields.value_inr),
            "emd": to_decimal(fields.emd_inr),
            "summary": fields.summary,
            "scope": to_pgvector(scope_vec),
        },
    )

    if not was_indexed:
        await session.execute(
            text("""
                INSERT INTO tender_events (tender_id, kind, new_value)
                SELECT :id, 'published', CAST(:v AS jsonb)
                WHERE NOT EXISTS (SELECT 1 FROM tender_events
                                  WHERE tender_id = :id AND kind = 'published')
            """),
            {"id": tender_id, "v": json.dumps({"industries": fields.industries})},
        )
        await queue.enqueue(
            session, "match_tender", {"tender_id": tender_id}, f"match_tender:{tender_id}"
        )
    elif trigger_doc is not None:
        await _handle_corrigendum(session, tender_id, int(trigger_doc), clauses)

    log.info(
        "indexed",
        tender_id=tender_id,
        clauses=len(clauses),
        embedded=len(todo),
        industries=fields.industries,
        corrigendum=was_indexed,
    )


async def _handle_corrigendum(
    session: AsyncSession, tender_id: int, document_id: int, clauses: Sequence[Any]
) -> None:
    """A new document on an already-indexed tender. If it touches eligibility, every org
    with a match on this tender gets its fit re-checked."""
    await session.execute(
        text("""
            INSERT INTO tender_events (tender_id, kind, document_id)
            SELECT :t, 'corrigendum', :d
            WHERE NOT EXISTS (SELECT 1 FROM tender_events
                              WHERE tender_id = :t AND kind = 'corrigendum' AND document_id = :d)
        """),
        {"t": tender_id, "d": document_id},
    )
    new_text = " ".join(
        f"{c.section or ''} {c.text}".lower() for c in clauses if c.document_id == document_id
    )
    if not any(w in new_text for w in ELIGIBILITY_WORDS):
        return
    orgs = (
        (
            await session.execute(
                text("""
                UPDATE matches SET needs_recheck = true, updated_at = now()
                WHERE tender_id = :t RETURNING org_id
            """),
                {"t": tender_id},
            )
        )
        .scalars()
        .all()
    )
    for org_id in orgs:
        await queue.enqueue(
            session,
            "fit_check",
            {"org_id": str(org_id), "tender_id": tender_id},
            f"fit_check:{org_id}:{tender_id}:doc{document_id}",
        )
    log.info("corrigendum_recheck", tender_id=tender_id, orgs=len(orgs))
