import time
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from core.config import get_settings
from core.db import session as db_session


@pytest.fixture
async def api(
    engine: AsyncEngine,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    # Point the app's global engine/sessionmaker at the test database.
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_sessionmaker", sessionmaker)
    async with sessionmaker() as s, s.begin():
        await s.execute(text("TRUNCATE rate_limits"))
    from apps.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def token(email: str, ttl: int = 300) -> dict[str, str]:
    secret = get_settings().auth_secret.get_secret_value()
    claims = {"sub": email, "aud": "tender-api", "exp": int(time.time()) + ttl}
    return {"Authorization": f"Bearer {jwt.encode(claims, secret, algorithm='HS256')}"}
