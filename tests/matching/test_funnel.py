import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.llm.embeddings import to_pgvector
from core.matching.funnel import match_profile, match_tender
from core.profiles.store import get_confirmed_profile

SM = async_sessionmaker[AsyncSession]
DIM = 1024


def vec(*weights: float) -> str:
    v = list(weights) + [0.0] * (DIM - len(weights))
    return to_pgvector(v)


async def _tender(
    s: AsyncSession,
    portal_id: int,
    ref: str,
    *,
    industries: list[str],
    state: str,
    central: bool = False,
    value: int | None = 5_000_000,
    live: bool = True,
    v: str,
) -> int:
    return int(
        (
            await s.execute(
                text("""
        INSERT INTO tenders (portal_id, tender_ref, title, industries, work_state, is_central,
                             value_inr, closes_at, pipeline_status, lifecycle_status,
                             scope_embedding)
        VALUES (:p, :ref, :ref, :ind, :state, :central, :value,
                now() + interval '10 days', 'indexed', :life, CAST(:v AS vector))
        RETURNING id"""),
                {
                    "p": portal_id,
                    "ref": ref,
                    "ind": industries,
                    "state": state,
                    "central": central,
                    "value": value,
                    "life": "open" if live else "closed",
                    "v": v,
                },
            )
        ).scalar_one()
    )


async def _org(s: AsyncSession, *, confirmed: bool, v: str, turnover: int = 3_200_000) -> uuid.UUID:
    org = uuid.uuid4()
    await s.execute(text("INSERT INTO orgs (id, name) VALUES (:o, 'x')"), {"o": org})
    await s.execute(
        text("""
        INSERT INTO company_profiles (org_id, version, industries, states, annual_turnover_inr,
                                      confirmed_at, profile_embedding)
        VALUES (:o, 1, '{electrical_works}', '{Delhi,Haryana}', :turnover,
                CASE WHEN :c THEN now() END, CAST(:v AS vector))"""),
        {"o": org, "c": confirmed, "v": v, "turnover": turnover},
    )
    return org


async def test_forward_funnel_filters_and_ranks(sessionmaker: SM, portal_id: int) -> None:
    async with sessionmaker() as s, s.begin():
        ids: dict[str, Any] = {}
        ids["A"] = await _tender(
            s, portal_id, "A", industries=["electrical_works"], state="Delhi", v=vec(1, 0.1)
        )
        ids["B"] = await _tender(
            s, portal_id, "B", industries=["electrical_works"], state="Maharashtra", v=vec(1, 0)
        )
        ids["C"] = await _tender(
            s,
            portal_id,
            "C",
            industries=["electrical_works"],
            state="Maharashtra",
            central=True,
            v=vec(1, 0.9),
        )
        ids["D"] = await _tender(
            s, portal_id, "D", industries=["it_services"], state="Delhi", v=vec(1, 0)
        )
        ids["E"] = await _tender(
            s,
            portal_id,
            "E",
            industries=["electrical_works"],
            state="Delhi",
            value=50_000_000,
            v=vec(1, 0),
        )  # > 32L / 0.3
        ids["F"] = await _tender(
            s,
            portal_id,
            "F",
            industries=["electrical_works"],
            state="Delhi",
            live=False,
            v=vec(1, 0),
        )
        ids["G"] = await _tender(
            s,
            portal_id,
            "G",
            industries=["electrical_works"],
            state="Haryana",
            value=None,
            v=vec(0.2, 1),
        )
        org = await _org(s, confirmed=True, v=vec(1, 0))
    async with sessionmaker() as s, s.begin():
        profile = await get_confirmed_profile(s, org)
        assert profile is not None
        results = await match_profile(s, profile)
        jobs = (
            await s.execute(text("SELECT count(*) FROM jobs WHERE kind = 'fit_check'"))
        ).scalar_one()
        stages = set((await s.execute(text("SELECT stage FROM matches"))).scalars())
    by_id = {v: k for k, v in ids.items()}
    assert [by_id[t] for t, _ in results] == ["A", "C", "G"]  # ranked by similarity
    assert jobs == 3 and stages == {"prefiltered"}


async def test_reverse_funnel_uses_only_confirmed_profiles(
    sessionmaker: SM, portal_id: int
) -> None:
    async with sessionmaker() as s, s.begin():
        tid = await _tender(
            s, portal_id, "A", industries=["electrical_works"], state="Delhi", v=vec(1, 0)
        )
        near = await _org(s, confirmed=True, v=vec(1, 0.1))
        far = await _org(s, confirmed=True, v=vec(0.3, 1))
        await _org(s, confirmed=False, v=vec(1, 0))  # draft only: never matched
        await _org(s, confirmed=True, v=vec(1, 0), turnover=100_000)  # too small for 50L
    async with sessionmaker() as s, s.begin():
        results = await match_tender(s, tid)
    assert [o for o, _ in results] == [near, far]


async def test_agent_checked_match_is_not_downgraded(sessionmaker: SM, portal_id: int) -> None:
    async with sessionmaker() as s, s.begin():
        tid = await _tender(
            s, portal_id, "A", industries=["electrical_works"], state="Delhi", v=vec(1, 0)
        )
        org = await _org(s, confirmed=True, v=vec(1, 0))
        await s.execute(
            text(
                "INSERT INTO matches (org_id, tender_id, stage, fit) "
                "VALUES (:o, :t, 'agent_checked', 'good')"
            ),
            {"o": org, "t": tid},
        )
    async with sessionmaker() as s, s.begin():
        await match_tender(s, tid)
        row = (await s.execute(text("SELECT stage, fit, score FROM matches"))).one()
    assert (row.stage, row.fit) == ("agent_checked", "good") and row.score is not None
