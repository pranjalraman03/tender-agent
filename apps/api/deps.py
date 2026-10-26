"""Auth, DB sessions and tenant scoping for API routes.

Auth: the Next.js server (Auth.js) signs a short-lived HS256 JWT with AUTH_SECRET for each
API call: {sub: email, name?, aud: "tender-api", exp}. On the first request from a new
email, an org and an owner user are created.

Sessions:
- public_db: reads public tender data (live_tenders only, by convention in routes).
- user_db: transaction scoped to the user's org (RLS via app.org_id) - rule 9.
- admin_db: system context; only after an admin role check.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.db.session import get_sessionmaker, set_org_context, system_transaction
from core.ratelimit import RateLimited, hit

AUDIENCE = "tender-api"


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _decode(token: str) -> dict[str, object]:
    secret = get_settings().auth_secret.get_secret_value()
    if not secret:
        raise HTTPException(500, "AUTH_SECRET is not configured")
    try:
        claims: dict[str, object] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "invalid token") from exc
    return claims


async def _load_or_provision(email: str, name: str | None) -> CurrentUser:
    """Find the user, creating them on first sign-in.

    Admins (ADMIN_EMAILS) belong to the demo company when one exists (scripts/seed_demo.py),
    so demo data is only ever seen by admins. Everyone else gets their own company.
    """
    email = email.strip().lower()
    admin = email in {e.lower() for e in get_settings().admin_emails}
    async with system_transaction() as s:
        demo_org = (
            await s.execute(text("SELECT id FROM orgs WHERE is_demo ORDER BY created_at LIMIT 1"))
        ).scalar_one_or_none()
        row = (
            await s.execute(
                text("SELECT id, org_id, role FROM users WHERE email = :e"), {"e": email}
            )
        ).one_or_none()
        if row is None:
            if admin and demo_org is not None:
                org_id = demo_org
            else:
                org_id = (
                    await s.execute(
                        text("INSERT INTO orgs (name) VALUES ('My company') RETURNING id")
                    )
                ).scalar_one()
            row = (
                await s.execute(
                    text(
                        "INSERT INTO users (org_id, email, name, role) VALUES (:o, :e, :n, :r) "
                        "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email "
                        "RETURNING id, org_id, role"
                    ),
                    {"o": org_id, "e": email, "n": name, "r": "admin" if admin else "owner"},
                )
            ).one()
        user_id, org_id, role = row.id, row.org_id, row.role
        if admin and (role != "admin" or (demo_org is not None and org_id != demo_org)):
            # Admins always work in the demo company when one exists.
            org_id = demo_org if demo_org is not None else org_id
            await s.execute(
                text("UPDATE users SET role = 'admin', org_id = :o WHERE id = :id"),
                {"o": org_id, "id": user_id},
            )
            role = "admin"
        elif not admin and role == "admin":
            # Removed from ADMIN_EMAILS: no longer an admin. If they were sitting in the demo
            # company, move them to a company of their own so they lose demo access too.
            new_org = org_id
            if org_id == demo_org:
                new_org = (
                    await s.execute(
                        text("INSERT INTO orgs (name) VALUES ('My company') RETURNING id")
                    )
                ).scalar_one()
            await s.execute(
                text("UPDATE users SET role = 'owner', org_id = :o WHERE id = :id"),
                {"o": new_org, "id": user_id},
            )
            role, org_id = "owner", new_org
    return CurrentUser(id=user_id, org_id=org_id, email=email, role=role)


async def optional_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "expected a Bearer token")
    claims = _decode(token)
    name = claims.get("name")
    return await _load_or_provision(str(claims["sub"]), str(name) if name else None)


async def current_user(user: Annotated[CurrentUser | None, Depends(optional_user)]) -> CurrentUser:
    if user is None:
        raise HTTPException(401, "sign in required")
    return user


async def admin_user(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


async def public_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session, session.begin():
        yield session


async def user_db(
    user: Annotated[CurrentUser, Depends(current_user)],
) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session, session.begin():
        await set_org_context(session, user.org_id)
        yield session


async def admin_db(
    user: Annotated[CurrentUser, Depends(admin_user)],
) -> AsyncIterator[AsyncSession]:
    async with system_transaction() as session:
        yield session


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )


async def rate_limit(bucket: str, limit: int, window_s: int) -> None:
    try:
        await hit(bucket, limit, window_s)
    except RateLimited as exc:
        raise HTTPException(
            429, "too many requests", headers={"Retry-After": str(exc.retry_after_s)}
        ) from exc


UserDB = Annotated[AsyncSession, Depends(user_db)]
PublicDB = Annotated[AsyncSession, Depends(public_db)]
AdminDB = Annotated[AsyncSession, Depends(admin_db)]
User = Annotated[CurrentUser, Depends(current_user)]
MaybeUser = Annotated[CurrentUser | None, Depends(optional_user)]
Admin = Annotated[CurrentUser, Depends(admin_user)]
