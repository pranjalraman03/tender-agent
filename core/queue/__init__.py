"""Postgres job queue.

Transaction rules (see CLAUDE.md, rules 3 and 4):
- `enqueue` never commits. Call it inside the same transaction as the data it relates to.
- `claim` is its own short transaction, committed by the caller, so other workers see
  the job as `running`.
- `complete` runs in the handler's transaction, so the handler's writes, its follow-up
  enqueues and `status = 'done'` commit together or not at all.
- `fail` runs in a fresh transaction after the handler's transaction has rolled back.

Idempotency: `idempotency_key` is UNIQUE and `enqueue` is `ON CONFLICT DO NOTHING`, so
enqueuing the same key twice is a no-op. Work that must legitimately repeat (e.g. an
hourly recheck) puts the time bucket in the key: `recheck:{tender_id}:{yyyy-mm-ddThh}`.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Retry delays after attempt 1, 2, 3, 4+.
BACKOFF = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
]

# Job kinds whose permanent failure marks the tender's pipeline as failed.
PIPELINE_KINDS = {"download", "parse", "index"}

DEFAULT_MAX_ATTEMPTS = 5
MAX_ERROR_CHARS = 4000


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    attempts: int
    max_attempts: int


def backoff_for(attempts: int) -> timedelta:
    """Delay before the next try, given how many attempts have been made (>= 1)."""
    return BACKOFF[min(max(attempts, 1), len(BACKOFF)) - 1]


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    *,
    run_after: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> int | None:
    """Add a job in the caller's transaction. Returns the new id, or None if the key exists."""
    result = await session.execute(
        text("""
            INSERT INTO jobs (kind, payload, idempotency_key, max_attempts, run_after)
            VALUES (:kind, CAST(:payload AS jsonb), :key, :max_attempts,
                    coalesce(:run_after, now()))
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
        """),
        {
            "kind": kind,
            "payload": json.dumps(payload),
            "key": idempotency_key,
            "max_attempts": max_attempts,
            "run_after": run_after,
        },
    )
    return result.scalar_one_or_none()


async def claim(session: AsyncSession) -> Job | None:
    """Take the next due job and mark it running. The caller commits."""
    row = (
        await session.execute(
            text("""
                UPDATE jobs
                SET status = 'running', attempts = attempts + 1,
                    locked_at = now(), updated_at = now()
                WHERE id = (
                    SELECT id FROM jobs
                    WHERE status = 'queued' AND run_after <= now()
                    ORDER BY run_after
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, kind, payload, idempotency_key, attempts, max_attempts
            """)
        )
    ).one_or_none()
    if row is None:
        return None
    return Job(
        id=row.id,
        kind=row.kind,
        payload=row.payload,
        idempotency_key=row.idempotency_key,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
    )


async def complete(session: AsyncSession, job_id: int) -> None:
    """Mark done, inside the handler's transaction."""
    await session.execute(
        text("""
            UPDATE jobs SET status = 'done', locked_at = NULL, updated_at = now()
            WHERE id = :id AND status = 'running'
        """),
        {"id": job_id},
    )


async def fail(session: AsyncSession, job: Job, error: str) -> str:
    """Record a failure: requeue with backoff, or dead-letter. Returns the new status."""
    error = error[:MAX_ERROR_CHARS]
    if job.attempts < job.max_attempts:
        await session.execute(
            text("""
                UPDATE jobs
                SET status = 'queued', run_after = now() + :delay,
                    locked_at = NULL, last_error = :error, updated_at = now()
                WHERE id = :id AND status = 'running'
            """),
            {"id": job.id, "delay": backoff_for(job.attempts), "error": error},
        )
        return "queued"

    await session.execute(
        text("""
            UPDATE jobs
            SET status = 'dead', locked_at = NULL, last_error = :error, updated_at = now()
            WHERE id = :id AND status = 'running'
        """),
        {"id": job.id, "error": error},
    )
    tender_id = job.payload.get("tender_id")
    if job.kind in PIPELINE_KINDS and tender_id is not None:
        await session.execute(
            text("""
                UPDATE tenders SET pipeline_status = 'failed', updated_at = now()
                WHERE id = :tender_id
            """),
            {"tender_id": int(tender_id)},
        )
    return "dead"


async def cancel_for_tender(session: AsyncSession, tender_id: int) -> int:
    """Cancel queued jobs for a tender (e.g. it closed). Returns how many were cancelled."""
    result = await session.execute(
        text("""
            UPDATE jobs SET status = 'cancelled', updated_at = now()
            WHERE status = 'queued' AND payload->>'tender_id' = :tender_id
        """),
        {"tender_id": str(tender_id)},
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def requeue_stuck(session: AsyncSession, timeouts_s: dict[str, int]) -> int:
    """Return `running` jobs whose lock is older than their kind's timeout to the queue.

    `timeouts_s` maps kind -> seconds, with a required "default" entry. A stuck job has
    already used up an attempt, so one that has no attempts left goes to `dead`.
    """
    rows = (
        await session.execute(
            text("""
                UPDATE jobs
                SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'dead' END,
                    run_after = now(),
                    locked_at = NULL,
                    last_error = 'stuck: lock timed out',
                    updated_at = now()
                WHERE status = 'running'
                  AND locked_at < now() - make_interval(
                        secs => coalesce((CAST(:timeouts AS jsonb) ->> kind)::int,
                                         (CAST(:timeouts AS jsonb) ->> 'default')::int))
                RETURNING kind, status, payload->>'tender_id' AS tender_id
            """),
            {"timeouts": json.dumps(timeouts_s)},
        )
    ).all()
    dead_tender_ids = [
        int(r.tender_id)
        for r in rows
        if r.status == "dead" and r.kind in PIPELINE_KINDS and r.tender_id is not None
    ]
    if dead_tender_ids:
        await session.execute(
            text("""
                UPDATE tenders SET pipeline_status = 'failed', updated_at = now()
                WHERE id = ANY(:ids)
            """),
            {"ids": dead_tender_ids},
        )
    return len(rows)
