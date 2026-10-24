"""All configuration comes from environment variables, validated here."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "production"] = "local"

    database_url: str

    storage_endpoint: str = ""
    storage_bucket: str = ""
    storage_access_key: SecretStr = SecretStr("")
    storage_secret_key: SecretStr = SecretStr("")

    anthropic_api_key: SecretStr = SecretStr("")
    llm_model_fast: str = ""
    llm_model_strong: str = ""

    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = ""
    embedding_dim: int = 1024

    rerank_api_key: SecretStr = SecretStr("")
    rerank_model: str = ""

    auth_secret: SecretStr = SecretStr("")

    resend_api_key: SecretStr = SecretStr("")
    email_from: str = ""

    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = ""

    sentry_dsn: str = ""

    crawler_user_agent: str = "TenderAgentBot/0.1"

    # Worker
    worker_poll_interval_s: float = 1.0
    # Seconds after which a `running` job is considered stuck, per kind.
    job_timeouts_s: dict[str, int] = {"default": 900}


@lru_cache
def get_settings() -> Settings:
    return Settings()
