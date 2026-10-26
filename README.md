# Tender Agent

Matches Indian MSMEs to live government tenders and checks eligibility clause by clause, with
every finding citing the tender document. See `CLAUDE.md` for the full design and rules, and
`docs/decisions/` for the decisions behind it.

## Run locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 20.9+, pnpm, and for OCR
`brew install tesseract ghostscript`.

```bash
# one-time
uv sync                                         # Python deps into .venv
cp .env.example .env                            # set AUTH_SECRET (openssl rand -base64 32), ADMIN_EMAILS
cp apps/web/.env.local.example apps/web/.env.local   # same AUTH_SECRET
docker compose -f infra/docker-compose.yml up -d postgres
uv run alembic upgrade head
uv run python scripts/seed.py
pnpm --dir apps/web install

# four terminals
uv run uvicorn apps.api.main:app --reload --port 8000
uv run python -m apps.worker.main
uv run python -m apps.scheduler.main
pnpm --dir apps/web dev                          # http://localhost:3000
```

The first embedding call downloads ~1.3 GB of local models into `var/models/`.

### What works without an API key
Crawling CPPP, the admin documents-needed queue, uploads, PDF parsing/OCR/chunking, clause
embeddings, search, profiles (manual + Udyam), matching stages 1-2, digests (to `var/outbox/`).

### What needs `ANTHROPIC_API_KEY`
Tender indexing (field extraction — so tenders only become *live* with a key), eligibility
reports, website profile extraction, per-tender chat. Set the key in `.env` and restart the
worker; queued jobs then run.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy core apps scripts evals
uv run pytest
uv run python evals/run_evals.py            # add --agent once the API key is set
pnpm --dir apps/web lint && pnpm --dir apps/web typecheck && pnpm --dir apps/web build
```

## Deploy with Docker (single server)

Everything runs in containers: `postgres`, `migrate` (one-shot), `api`, `worker`,
`scheduler`, `web`. Only `web` is exposed. See ADR 0008.

```bash
cp infra/.env.deploy.example infra/.env.deploy      # fill in secrets on the server only
docker compose -f infra/docker-compose.deploy.yml --env-file infra/.env.deploy up -d --build
docker compose -f infra/docker-compose.deploy.yml --env-file infra/.env.deploy ps
docker compose -f infra/docker-compose.deploy.yml --env-file infra/.env.deploy logs -f worker
```

- Development login is always off in this stack: set `RESEND_API_KEY` and/or Google OAuth.
- Put a TLS proxy (e.g. Caddy) in front of port 3000 and set `PUBLIC_URL` to the https address.
- The first embedding call downloads the local models (~1.3 GB) into the `models` volume.
