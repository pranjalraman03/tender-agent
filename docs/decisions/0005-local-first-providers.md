# 0005 — Local-first providers for development

**Status:** accepted · 2026-10-25

Everything runs locally without third-party keys except the Claude API:

| Concern | Local default | Production option |
| --- | --- | --- |
| Object storage | `STORAGE_BACKEND=local` (folder `var/storage`) | Cloudflare R2 via S3 API (`s3`) |
| Embeddings | `bge-large-en-v1.5` via fastembed (ONNX, 1024-d) | Voyage AI (`voyage`), same dimension |
| Reranker | `ms-marco-MiniLM-L-6-v2` cross-encoder (ONNX) | Voyage rerank |
| Email | written to `var/outbox/*.html` | Resend |
| Sign-in | dev email login (`AUTH_DEV_LOGIN`, never in production builds) | Resend magic link, Google |

LLM-dependent job kinds (index, fit_check, extract_profile) are only registered by the worker
when `ANTHROPIC_API_KEY` is set; until then their jobs wait in the queue instead of failing.

Why: the app can be exercised end to end on a laptop at zero cost, and each provider sits behind
one module (`core/storage.py`, `core/llm/embeddings.py`, `core/email.py`), so switching is config.
Changing the embedding model requires re-embedding all clauses and profiles.
