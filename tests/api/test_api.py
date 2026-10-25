import uuid
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import get_settings
from core.reference.industries import seed_reference_data
from tests.api.conftest import token

SM = async_sessionmaker[AsyncSession]


async def _tenders(sm: SM, portal_id: int) -> dict[str, int]:
    out = {}
    async with sm() as s, s.begin():
        await seed_reference_data(s)
        for ref, pipeline, life, offset in [
            ("live", "indexed", "open", timedelta(days=5)),
            ("expired", "indexed", "open", timedelta(hours=-1)),
            ("closed", "indexed", "closed", timedelta(days=5)),
            ("raw", "discovered", "open", timedelta(days=5)),
        ]:
            out[ref] = (
                await s.execute(
                    text(
                        "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, "
                        "lifecycle_status, closes_at, work_state, industries) VALUES (:p, :r, :r, :pl, "
                        ":lc, now() + :off, 'Delhi', '{electrical_works}') "
                        "RETURNING id"
                    ),
                    {"p": portal_id, "r": ref, "pl": pipeline, "lc": life, "off": offset},
                )
            ).scalar_one()
    return out


async def test_public_feed_shows_only_live_tenders(
    api: httpx.AsyncClient, sessionmaker: SM, portal_id: int
) -> None:
    ids = await _tenders(sessionmaker, portal_id)
    feed = (await api.get("/tenders")).json()
    assert [t["title"] for t in feed["items"]] == ["live"] and feed["total"] == 1
    for ref in ("expired", "closed", "raw"):
        assert (await api.get(f"/tenders/{ids[ref]}")).status_code == 404
    assert (await api.get(f"/tenders/{ids['live']}")).status_code == 200
    filtered = (await api.get("/tenders", params={"state": "Kerala"})).json()
    assert filtered["total"] == 0


async def test_auth_required_and_auto_provisioning(api: httpx.AsyncClient) -> None:
    assert (await api.get("/me")).status_code == 401
    assert (await api.get("/me", headers={"Authorization": "Bearer junk"})).status_code == 401
    expired = token("a@x.test", ttl=-10)
    assert (await api.get("/me", headers=expired)).status_code == 401
    me = (await api.get("/me", headers=token("A@X.test"))).json()
    again = (await api.get("/me", headers=token("a@x.test"))).json()
    assert me["email"] == "a@x.test" and me["org"]["id"] == again["org"]["id"]
    assert me["role"] == "owner" and me["has_confirmed_profile"] is False


async def test_orgs_cannot_see_each_others_matches(
    api: httpx.AsyncClient, sessionmaker: SM, portal_id: int
) -> None:
    ids = await _tenders(sessionmaker, portal_id)
    a = (await api.get("/me", headers=token("a@x.test"))).json()["org"]["id"]
    b = (await api.get("/me", headers=token("b@y.test"))).json()["org"]["id"]
    async with sessionmaker() as s, s.begin():
        for org in (a, b):
            await s.execute(
                text(
                    "INSERT INTO matches (org_id, tender_id, stage, fit) "
                    "VALUES (:o, :t, 'prefiltered', 'good')"
                ),
                {"o": uuid.UUID(org), "t": ids["live"]},
            )
        await s.execute(
            text("INSERT INTO matches (org_id, tender_id, stage) VALUES (:o, :t, 'prefiltered')"),
            {"o": uuid.UUID(a), "t": ids["expired"]},
        )
    got_a = (await api.get("/matches", headers=token("a@x.test"))).json()
    assert [m["tender"]["id"] for m in got_a] == [ids["live"]]  # expired tender hidden
    # B dismisses its match; A's is unaffected.
    r = await api.patch(
        f"/matches/{ids['live']}", json={"user_state": "dismissed"}, headers=token("b@y.test")
    )
    assert r.status_code == 200
    assert (await api.get("/matches", headers=token("a@x.test"))).json()[0]["user_state"] is None
    assert (await api.get("/matches", headers=token("b@y.test"))).json() == []


async def test_profile_flow_over_http(api: httpx.AsyncClient, sessionmaker: SM) -> None:
    async with sessionmaker() as s, s.begin():
        await seed_reference_data(s)
    h = token("owner@co.test")
    assert (await api.post("/profile/confirm", headers=h)).status_code == 422  # no draft
    r = await api.patch(
        "/profile",
        headers=h,
        json={
            "company_name": "Brightline",
            "industries": ["electrical_works"],
            "states": ["Delhi"],
            "annual_turnover_inr": 3200000,
            "past_projects": [{"title": "Street lights AMC", "value_inr": 2600000, "year": 2025}],
        },
    )
    assert r.status_code == 200 and r.json()["draft"]["industries"] == ["electrical_works"]
    bad = await api.patch("/profile", headers=h, json={"states": ["Atlantis"]})
    assert bad.status_code == 422
    done = (await api.post("/profile/confirm", headers=h)).json()
    assert done["draft"] is None and done["confirmed"]["version"] == 1
    me = (await api.get("/me", headers=h)).json()
    assert me["org"]["name"] == "Brightline" and me["has_confirmed_profile"]


async def test_admin_routes_need_admin(
    api: httpx.AsyncClient, sessionmaker: SM, portal_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await _tenders(sessionmaker, portal_id)
    assert (await api.get("/admin/overview", headers=token("user@co.test"))).status_code == 403
    monkeypatch.setattr(get_settings(), "admin_emails", ["boss@co.test"])
    h = token("boss@co.test")
    assert (await api.get("/admin/overview", headers=h)).status_code == 200
    needed = (await api.get("/admin/documents-needed", headers=h)).json()
    # Both open tenders lack documents; the closed and expired ones are not listed.
    assert {n["tender_id"] for n in needed} == {ids["raw"], ids["live"]}
    assert all(n["reason"] == "no_documents" for n in needed)


async def test_rate_limit_returns_429(api: httpx.AsyncClient, sessionmaker: SM) -> None:
    from fastapi import HTTPException

    from apps.api.deps import rate_limit

    for _ in range(3):
        await rate_limit("test-bucket", limit=3, window_s=60)
    with pytest.raises(HTTPException) as exc:
        await rate_limit("test-bucket", limit=3, window_s=60)
    assert exc.value.status_code == 429 and "Retry-After" in (exc.value.headers or {})


async def test_chat_without_key_is_503(
    api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, sessionmaker: SM, portal_id: int
) -> None:
    ids = await _tenders(sessionmaker, portal_id)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", SecretStr(""))
    r = await api.post(
        f"/tenders/{ids['live']}/chat",
        json={"session_id": str(uuid.uuid4()), "question": "What is the EMD?"},
    )
    assert r.status_code == 503


async def test_request_eligibility_check(
    api: httpx.AsyncClient, sessionmaker: SM, portal_id: int
) -> None:
    ids = await _tenders(sessionmaker, portal_id)
    h = token("checker@co.test")
    assert (await api.post(f"/reports/{ids['live']}/check", headers=h)).status_code == 409
    await api.patch(
        "/profile", headers=h, json={"industries": ["electrical_works"], "states": ["Delhi"]}
    )
    await api.post("/profile/confirm", headers=h)
    assert (await api.post(f"/reports/{ids['expired']}/check", headers=h)).status_code == 404
    for _ in range(2):
        r = await api.post(f"/reports/{ids['live']}/check", headers=h)
        assert r.status_code == 202
    async with sessionmaker() as s:
        n = (await s.execute(text("SELECT count(*) FROM jobs WHERE kind = 'fit_check'"))).scalar()
    assert n == 1  # idempotent per profile version
    status = (await api.get(f"/reports/{ids['live']}/status", headers=h)).json()
    assert status["status"] == "queued"
