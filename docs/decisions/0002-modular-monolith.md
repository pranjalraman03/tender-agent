# 0002 — Modular monolith, one database

**Status:** accepted · 2026-10-24

## Decision
One Python package (`core/`) run as three processes — `api`, `worker`, `scheduler` — from one
Docker image, plus the Next.js `web` app. All share one Postgres (with pgvector). Modules talk
only through the database and the job queue, never over HTTP.

## Why
- One deploy unit and one schema keep a solo project explainable and cheap.
- Postgres covers rows, vectors, full-text, queue and rate limiting at this scale.
- Process separation still lets the worker scale and crash independently of the API.

## Rules that keep it modular
- `apps/*` import `core`; `core` never imports `apps`.
- Features inside `core` use each other's public functions, the DB, or a job — not internals.

## Revisit when
Worker load needs different hardware (e.g. OCR or a browser), or one module needs its own
release cadence.
