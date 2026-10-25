"""Logging (structlog), errors (Sentry, if SENTRY_DSN is set) and LLM tracing.

LLM traces: every Claude call is logged to `llm_calls` with a trace_id (one per eligibility
run / chat session / index run), and eligibility reports store their trace_id. Langfuse
export is optional and not wired in v1 local development."""

import logging

import structlog

from core.config import get_settings


def configure_logging(json_logs: bool = True) -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def init_sentry(process: str) -> None:
    dsn = get_settings().sentry_dsn
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=get_settings().app_env,
        server_name=process,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
