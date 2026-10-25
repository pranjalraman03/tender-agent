# 0004 — Captcha-gated documents: human upload, never bypass

**Status:** accepted · 2026-10-25

## Context
CPPP (and other NIC GePNIC portals) publish tender listings and detail pages openly, but the
full listing search and every document download sit behind a captcha. The product needs the
PDFs: eligibility findings must cite clauses.

## Decision
We never solve or bypass captchas automatically (CLAUDE.md rule 11; also likely unauthorised
access, and it gets crawlers blocked). Instead:
- The crawler stores tenders from public pages only (metadata, `discovered`).
- The `download` job exits cleanly for portals without open document access.
- An admin "documents needed" queue lists open tenders without documents (soonest deadline
  first) plus tenders with a corrigendum newer than their latest document. A person opens the
  portal, solves the captcha, downloads, and uploads the PDF/ZIP. Everything after is automatic.
- Signed-in users can add documents (e.g. corrigenda) to live tenders.
- Corrigenda/extensions are detected from the portal's public "Latest Corrigendum" table.

## Consequences
Coverage is bounded by human upload capacity, so the focus industries matter. Longer term:
portals with open documents (new crawler per portal), or official / licensed data access.
