from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import admin, chat, health, matches, profiles, tenders
from core.config import get_settings
from core.observability import configure_logging, init_sentry

settings = get_settings()
configure_logging(json_logs=settings.app_env == "production")
init_sentry("api")

app = FastAPI(title="Tender Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for module in (health, tenders, chat, profiles, matches, admin):
    app.include_router(module.router)
