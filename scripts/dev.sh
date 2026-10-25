#!/usr/bin/env bash
# Start the whole stack locally: Postgres (Docker), migrations, API, worker, scheduler, web.
# Ctrl-C stops the app processes; Postgres keeps running in Docker.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Start Docker Desktop and try again." >&2
  exit 1
fi
docker compose -f infra/docker-compose.yml up -d --wait postgres
uv run alembic upgrade head
uv run python scripts/seed.py

pids=()
trap 'echo; echo "stopping..."; kill "${pids[@]}" 2>/dev/null || true; wait' INT TERM EXIT
uv run uvicorn apps.api.main:app --reload --port 8000 & pids+=($!)
uv run python -m apps.worker.main & pids+=($!)
uv run python -m apps.scheduler.main & pids+=($!)
pnpm --dir apps/web dev & pids+=($!)
echo "Tender Agent: http://localhost:3000  (API http://localhost:8000/docs)"
wait
