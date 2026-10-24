import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db.session import set_org_context

SM = async_sessionmaker[AsyncSession]


async def test_live_tenders_only_shows_open_indexed_future_tenders(
    sessionmaker: SM, portal_id: int
) -> None:
    rows = [
        # ref, pipeline, lifecycle, closes_at offset, expected visible
        ("live", "indexed", "open", timedelta(days=1), True),
        ("extended", "indexed", "extended", timedelta(days=1), True),
        ("past_deadline", "indexed", "open", timedelta(minutes=-1), False),
        ("not_indexed", "parsed", "open", timedelta(days=1), False),
        ("closed", "indexed", "closed", timedelta(days=1), False),
        ("cancelled", "indexed", "cancelled", timedelta(days=1), False),
    ]
    async with sessionmaker() as s, s.begin():
        for ref, pipeline, lifecycle, offset, _ in rows:
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, "
                    "lifecycle_status, closes_at) VALUES (:p, :ref, 't', :pl, :lc, "
                    "now() + :off)"
                ),
                {"p": portal_id, "ref": ref, "pl": pipeline, "lc": lifecycle, "off": offset},
            )
    async with sessionmaker() as s:
        visible = set((await s.execute(text("SELECT tender_ref FROM live_tenders"))).scalars())
    assert visible == {ref for ref, *_, ok in rows if ok}


async def test_rls_scopes_tenant_rows_to_current_org(sessionmaker: SM, portal_id: int) -> None:
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    async with sessionmaker() as s, s.begin():
        tender_id = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title) VALUES (:p, 'T', 't') "
                    "RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
        for org in (org_a, org_b):
            await s.execute(text("INSERT INTO orgs (id, name) VALUES (:id, 'o')"), {"id": org})
            await s.execute(
                text(
                    "INSERT INTO matches (org_id, tender_id, stage) VALUES (:o, :t, 'prefiltered')"
                ),
                {"o": org, "t": tender_id},
            )

    async with sessionmaker() as s, s.begin():
        await s.execute(text("SET LOCAL ROLE tender_app_test"))
        # No org context: nothing visible.
        assert (await s.execute(text("SELECT count(*) FROM matches"))).scalar_one() == 0
        await set_org_context(s, org_a)
        orgs = list((await s.execute(text("SELECT org_id FROM matches"))).scalars())
        assert orgs == [org_a]
        # Writing a row for another org is rejected by WITH CHECK.
        await s.execute(text("SAVEPOINT sp"))
        try:
            await s.execute(
                text("INSERT INTO orgs (id, name) VALUES (:id, 'x')"), {"id": uuid.uuid4()}
            )
            raised = False
        except Exception:
            raised = True
        assert raised
