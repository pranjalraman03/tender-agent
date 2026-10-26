# 0008 — Every service in a container; one compose file for a single server

**Status:** accepted · 2026-10-26

## Decision
- `infra/Dockerfile.backend`: one multi-stage image (Python 3.12, uv-locked deps, Tesseract +
  Ghostscript for OCR) for the `api`, `worker`, `scheduler` and one-shot `migrate` services,
  which differ only by start command. Non-root user (uid 10001); data in `/data` volumes.
- `infra/Dockerfile.web`: Next.js standalone server, non-root.
- `infra/docker-compose.deploy.yml` runs the whole stack on one server: only `web` publishes a
  port; Postgres, API, worker and scheduler are on the private network. Uploaded documents and
  local models live in named volumes shared by `api` and `worker`.
- `migrate` runs on every deploy (migrations, reference data, app role) and the other services
  start only after it succeeds.
- The app connects as `tender_app` (no superuser, no BYPASSRLS) so row-level security applies;
  only `migrate` uses the owner account (`scripts/create_app_role.py`, idempotent).
- Secrets live only in `infra/.env.deploy` on the server (git- and docker-ignored); the
  committed template has no values. Docker reads env values literally, so comments go on
  their own lines.
- Images are multi-arch; tested on arm64 (same as Oracle Cloud's free Ampere VMs).

## Why
No dependency conflicts on the server (system OCR tools, Python and Node versions are pinned in
images), identical builds on any host, and the same images can later run on Railway or similar.

## Not covered yet
TLS termination (put Caddy or similar in front of `web:3000`), off-server database backups, and
image registry / CI publishing.
