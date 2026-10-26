# 0003 — Tenant isolation with Postgres row-level security

**Status:** accepted · 2026-10-24

## Decision
Every tenant table carries `org_id` and has RLS enabled and FORCEd. Policies read two
transaction-local settings:

- `app.org_id` — set by the API per request (`set_org_context`). Rows are visible only when
  they match.
- `app.role = 'system'` — set by the worker, scheduler, admin and evals
  (`set_system_context`), which legitimately work across orgs.

Anonymous chat rows (`org_id IS NULL`) are scoped by `app.chat_session_id`.

API queries still filter by `org_id` explicitly; RLS is the backstop if one forgets.

## Important
**Superusers and roles with BYPASSRLS ignore RLS entirely.** The application must connect as a
plain role (`scripts/create_app_role.py`), and migrations as the owner. The local Docker
user is a superuser, so the RLS test switches to a non-superuser role with `SET LOCAL ROLE`.

## Trade-off
A process in system context can see everything, so the `system` setting must never be
reachable from request handling in the API (except admin routes).
