# 0006 — Auth between Next.js and FastAPI; frontend rendering

**Status:** accepted · 2026-10-25

## Auth
Auth.js v5 (Next.js) handles sign-in; its tables live in a separate Postgres schema `auth`
(migration 0005) so they never collide with the app's `users`. Sessions are JWT cookies.

For each API call the Next.js server mints a 5-minute HS256 token (`sub` = email,
`aud` = tender-api) with the shared `AUTH_SECRET`; FastAPI verifies it and provisions an org +
user on first sight. Browser calls go through `/api/backend/*` on the Next.js server, so API
tokens never reach the browser and there is no CORS surface. SSE streams and uploads are passed
through unchanged.

## Rendering
Next.js 16 with Cache Components **off**: pages render per request and fetch FastAPI directly
(public pages as server components for SEO; interactive parts with TanStack Query). This keeps
the data flow explicit; Cache Components can be adopted later route by route.
