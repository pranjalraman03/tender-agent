"""All configuration comes from environment variables, validated here."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: a blank `KEY=` line in .env falls back to the default below.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    app_env: Literal["local", "production"] = "local"

    database_url: str

    # Storage. "local" writes to a folder (development without R2 keys); "s3" is any
    # S3-compatible bucket, e.g. Cloudflare R2: https://<account_id>.r2.cloudflarestorage.com
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "var/storage"
    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_access_key: SecretStr = SecretStr("")
    storage_secret_key: SecretStr = SecretStr("")

    # LLM provider. "anthropic" = Claude API (production design). "openai_compat" = any
    # OpenAI-compatible API, default Groq's free tier with open-weight models, for testing
    # without a Claude key.
    llm_provider: Literal["anthropic", "openai_compat"] = "anthropic"
    openai_compat_base_url: str = "https://api.groq.com/openai/v1"
    openai_compat_api_key: SecretStr = SecretStr("")
    openai_compat_model_fast: str = "openai/gpt-oss-20b"
    openai_compat_model_strong: str = "openai/gpt-oss-120b"

    # Claude. Model IDs per https://docs.claude.com (checked 2026-10-25).
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model_fast: str = "claude-sonnet-5-5"  # extraction, classification, verification
    llm_model_strong: str = "claude-opus-5-5"  # eligibility check
    llm_refusal_fallback: bool = True  # server-side fallback model if a request is refused

    # Embeddings / rerank. "local" runs ONNX models on this machine (no key needed);
    # "voyage" is the hosted Voyage AI API.
    embedding_provider: Literal["local", "voyage"] = "local"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: int = 1024
    rerank_provider: Literal["local", "voyage", "none"] = "local"
    rerank_api_key: SecretStr = SecretStr("")
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    model_cache_dir: str = "var/models"

    # Matching. Max tender value = turnover / this ratio (CPWD norm: turnover >= 30% of the
    # estimated cost). Tenders without a value, or profiles without turnover, aren't filtered.
    match_min_turnover_ratio: float = 0.3
    match_shortlist: int = 50  # stage 2 limit
    match_fit_check_top: int = 30  # stage 3: agent runs on this many

    # Agent budgets per eligibility run.
    agent_max_tool_calls: int = 40
    agent_max_tokens: int = 400_000
    agent_timeout_s: int = 300

    auth_secret: SecretStr = SecretStr("")
    admin_emails: list[str] = []  # JSON list in env, e.g. ADMIN_EMAILS=["you@example.com"]
    cors_origins: list[str] = ["http://localhost:3000"]

    resend_api_key: SecretStr = SecretStr("")
    email_from: str = "Tender Agent <digest@example.com>"
    web_base_url: str = "http://localhost:3000"

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "https://cloud.langfuse.com"

    sentry_dsn: str = ""

    crawler_user_agent: str = "TenderAgentBot/0.1"

    # Profile website extraction (SSRF-guarded fetch limits).
    fetch_max_pages: int = 8
    fetch_max_bytes: int = 2_000_000
    fetch_timeout_s: float = 10.0

    # Worker
    worker_poll_interval_s: float = 1.0
    worker_concurrency: int = 4
    # Seconds after which a `running` job is considered stuck, per kind.
    job_timeouts_s: dict[str, int] = {"default": 900, "parse": 1800, "fit_check": 900}

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "openai_compat":
            return bool(self.openai_compat_api_key.get_secret_value())
        return bool(self.anthropic_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
