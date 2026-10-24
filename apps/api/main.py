from fastapi import FastAPI

from apps.api.routes import health
from core.config import get_settings
from core.observability import configure_logging

configure_logging(json_logs=get_settings().app_env == "production")

app = FastAPI(title="Tender Agent API")
app.include_router(health.router)
