# 0001 — Job queue in Postgres

**Status:** accepted · 2026-10-24

## Context
Pipeline steps (crawl → download → parse → index → match) write data and create follow-up
work. If the write commits and the enqueue doesn't (or the other way round), tenders get stuck
or processed twice. We also need per-job retries with backoff, a dead-letter state, and
cancellation when a tender closes.

## Decision
A `jobs` table in the main Postgres database, claimed with
`UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`.

- `enqueue` runs in the caller's transaction, so data and follow-up jobs commit together.
- `idempotency_key` is UNIQUE; enqueue is `ON CONFLICT DO NOTHING`. Repeating work puts a
  time bucket in the key.
- A handler's writes and `status = 'done'` commit in one transaction. On error that
  transaction rolls back and a fresh one records the failure: requeue with backoff
  (1 m, 5 m, 30 m, 2 h) or `dead`.
- The scheduler requeues `running` jobs whose lock is older than the kind's timeout.

## Alternatives
- **Redis/RQ/Celery:** another service to run, and no transactional enqueue with our data.
- **Kafka/SQS:** built for throughput we don't need; per-message retry/backoff and
  cancellation are awkward; no shared transaction with Postgres.

## Consequences
- Throughput is bounded by Postgres, which is far above our needs (thousands of jobs/day).
- Database effects are exactly-once: a job's writes and `done` commit together, so a crash
  before commit leaves nothing behind and the whole job re-runs. External side effects
  (HTTP fetches, bucket uploads) are at-least-once, so handlers must still be idempotent.
