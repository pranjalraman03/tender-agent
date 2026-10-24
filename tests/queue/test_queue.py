import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import queue
from core.queue.worker import run_once

SM = async_sessionmaker[AsyncSession]


async def _job_row(sm: SM, job_id: int) -> Any:
    async with sm() as s:
        return (await s.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id})).one()


async def _enqueue(sm: SM, key: str, kind: str = "noop", **kw: Any) -> int:
    async with sm() as s, s.begin():
        job_id = await queue.enqueue(s, kind, kw.pop("payload", {}), key, **kw)
    assert job_id is not None
    return job_id


async def test_enqueue_is_idempotent(sessionmaker: SM) -> None:
    first = await _enqueue(sessionmaker, "k1")
    async with sessionmaker() as s, s.begin():
        second = await queue.enqueue(s, "noop", {}, "k1")
    assert second is None
    async with sessionmaker() as s:
        assert (await s.execute(text("SELECT count(*) FROM jobs"))).scalar_one() == 1
    assert first > 0


async def test_enqueue_rolls_back_with_callers_transaction(sessionmaker: SM) -> None:
    async with sessionmaker() as s:
        async with s.begin():
            await queue.enqueue(s, "noop", {}, "k1")
            await s.rollback()
    async with sessionmaker() as s:
        assert (await s.execute(text("SELECT count(*) FROM jobs"))).scalar_one() == 0


async def test_claim_marks_running_and_skips_future_jobs(sessionmaker: SM) -> None:
    async with sessionmaker() as s, s.begin():
        await queue.enqueue(s, "noop", {}, "later", run_after=await _now_plus(s, minutes=10))
    job_id = await _enqueue(sessionmaker, "now")

    async with sessionmaker() as s, s.begin():
        job = await queue.claim(s)
    assert job is not None and job.id == job_id and job.attempts == 1
    row = await _job_row(sessionmaker, job_id)
    assert row.status == "running" and row.locked_at is not None

    async with sessionmaker() as s, s.begin():
        assert await queue.claim(s) is None  # only the future job is left


async def _now_plus(s: AsyncSession, **delta: float) -> Any:
    now = (await s.execute(text("SELECT now()"))).scalar_one()
    return now + timedelta(**delta)


async def test_concurrent_claims_never_return_the_same_job(sessionmaker: SM) -> None:
    for i in range(20):
        await _enqueue(sessionmaker, f"k{i}")

    async def claim_one() -> int | None:
        async with sessionmaker() as s, s.begin():
            job = await queue.claim(s)
            await asyncio.sleep(0.05)  # hold the row lock while others try
            return job.id if job else None

    ids = [i for i in await asyncio.gather(*(claim_one() for _ in range(20))) if i]
    assert len(ids) == 20
    assert len(set(ids)) == 20


async def test_fail_backs_off_then_dead_letters_and_fails_tender(
    sessionmaker: SM, portal_id: int
) -> None:
    async with sessionmaker() as s, s.begin():
        tender_id = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title) "
                    "VALUES (:p, 'T1', 't') RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
    job_id = await _enqueue(
        sessionmaker, "dl", kind="download", payload={"tender_id": tender_id}, max_attempts=2
    )

    async with sessionmaker() as s, s.begin():
        job = await queue.claim(s)
    assert job is not None
    async with sessionmaker() as s, s.begin():
        assert await queue.fail(s, job, "boom") == "queued"
    row = await _job_row(sessionmaker, job_id)
    assert row.status == "queued" and row.last_error == "boom"
    assert row.run_after - row.updated_at >= timedelta(minutes=1) - timedelta(seconds=1)

    async with sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE jobs SET run_after = now() WHERE id = :id"), {"id": job_id})
        job = await queue.claim(s)
    assert job is not None and job.attempts == 2
    async with sessionmaker() as s, s.begin():
        assert await queue.fail(s, job, "boom again") == "dead"

    assert (await _job_row(sessionmaker, job_id)).status == "dead"
    async with sessionmaker() as s:
        status = (
            await s.execute(
                text("SELECT pipeline_status FROM tenders WHERE id = :id"), {"id": tender_id}
            )
        ).scalar_one()
    assert status == "failed"


def test_backoff_schedule() -> None:
    assert [queue.backoff_for(n) for n in (1, 2, 3, 4, 9)] == [
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=30),
        timedelta(hours=2),
        timedelta(hours=2),
    ]


async def test_run_once_commits_handler_writes_and_followups_with_done(sessionmaker: SM) -> None:
    job_id = await _enqueue(sessionmaker, "parent", kind="parent")

    async def handler(payload: dict[str, Any], session: AsyncSession) -> None:
        await queue.enqueue(session, "child", {}, "child-of-parent")

    assert await run_once(sessionmaker, {"parent": handler}) is True
    assert (await _job_row(sessionmaker, job_id)).status == "done"
    async with sessionmaker() as s:
        assert (
            await s.execute(
                text("SELECT status FROM jobs WHERE idempotency_key = 'child-of-parent'")
            )
        ).scalar_one() == "queued"


async def test_run_once_rolls_back_handler_writes_on_failure(sessionmaker: SM) -> None:
    job_id = await _enqueue(sessionmaker, "parent", kind="parent")

    async def handler(payload: dict[str, Any], session: AsyncSession) -> None:
        await queue.enqueue(session, "child", {}, "child-of-parent")
        raise RuntimeError("handler broke")

    assert await run_once(sessionmaker, {"parent": handler}) is True
    row = await _job_row(sessionmaker, job_id)
    assert row.status == "queued" and "handler broke" in row.last_error
    async with sessionmaker() as s:
        assert (await s.execute(text("SELECT count(*) FROM jobs"))).scalar_one() == 1


async def test_run_once_unknown_kind_fails_job(sessionmaker: SM) -> None:
    job_id = await _enqueue(sessionmaker, "x", kind="no_such_kind")
    assert await run_once(sessionmaker, {}) is True
    assert (await _job_row(sessionmaker, job_id)).status == "queued"


async def test_run_once_with_empty_queue(sessionmaker: SM) -> None:
    assert await run_once(sessionmaker, {}) is False


async def test_requeue_stuck(sessionmaker: SM) -> None:
    stuck = await _enqueue(sessionmaker, "stuck")
    fresh = await _enqueue(sessionmaker, "fresh")
    async with sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = 1, "
                "locked_at = now() - interval '1 hour' WHERE id = :id"
            ),
            {"id": stuck},
        )
        await s.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = 1, locked_at = now() WHERE id = :id"
            ),
            {"id": fresh},
        )
    async with sessionmaker() as s, s.begin():
        assert await queue.requeue_stuck(s, {"default": 900}) == 1
    assert (await _job_row(sessionmaker, stuck)).status == "queued"
    assert (await _job_row(sessionmaker, fresh)).status == "running"


async def test_cancel_for_tender(sessionmaker: SM) -> None:
    a = await _enqueue(sessionmaker, "a", payload={"tender_id": 7})
    b = await _enqueue(sessionmaker, "b", payload={"tender_id": 8})
    async with sessionmaker() as s, s.begin():
        assert await queue.cancel_for_tender(s, 7) == 1
    assert (await _job_row(sessionmaker, a)).status == "cancelled"
    assert (await _job_row(sessionmaker, b)).status == "queued"
