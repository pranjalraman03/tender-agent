"""Agent loop mechanics with a scripted fake Claude (no API calls)."""

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.agent.loop import compute_verdict, run_eligibility
from core.agent.schemas import Finding
from core.jobs import fit_check
from core.llm.claude import Usage
from core.llm.embeddings import embed, to_pgvector

SM = async_sessionmaker[AsyncSession]

CLAUSES = [
    (
        "4.1",
        "Eligibility",
        "Average annual turnover in the last 3 years shall be at least Rs. 50 lakh.",
    ),
    ("4.2", "Eligibility", "The bidder must hold a valid ISO 9001 certificate."),
    ("6", "EMD", "MSEs registered with Udyam are exempt from paying EMD."),
]


def _msg(stop: str, blocks: list[Any]) -> Any:
    return SimpleNamespace(stop_reason=stop, content=blocks)


def _text(data: Any) -> Any:
    return SimpleNamespace(type="text", text=json.dumps(data))


class ScriptedClaude:
    """Answers by purpose. The check step first calls compare_numeric, then answers."""

    def __init__(self, clause_ids: dict[str, int], verify_ok: bool = True) -> None:
        self.ids = clause_ids
        self.verify_ok = verify_ok
        self.check_turn = 0
        self.tool_results: list[Any] = []
        self.purposes: list[str] = []

    async def create(self, ctx: Any, **kw: Any) -> tuple[Any, Usage]:
        self.purposes.append(ctx.purpose)
        usage = Usage(input_tokens=100, output_tokens=50, calls=1, models={"fake"})
        if ctx.purpose == "agent_plan":
            return _msg(
                "end_turn",
                [
                    _text(
                        {
                            "criteria": [
                                {
                                    "id": "C1",
                                    "description": "Average turnover >= Rs 50 lakh",
                                    "category": "turnover",
                                    "clause_ids": [self.ids["4.1"]],
                                },
                                {
                                    "id": "C2",
                                    "description": "ISO 9001 certificate",
                                    "category": "certification",
                                    "clause_ids": [self.ids["4.2"], 999999],
                                },  # bogus id must be dropped
                            ]
                        }
                    )
                ],
            ), usage
        if ctx.purpose == "agent_check":
            self.check_turn += 1
            if self.check_turn == 1:
                return _msg(
                    "tool_use",
                    [
                        SimpleNamespace(
                            type="tool_use",
                            id="t1",
                            name="compare_numeric",
                            input={"requirement": "50 lakh", "actual": "62,00,000", "rule": ">="},
                        )
                    ],
                ), usage
            self.tool_results = kw["messages"][-1]["content"]
            return _msg(
                "end_turn",
                [
                    _text(
                        {
                            "findings": [
                                {
                                    "criterion_id": "C1",
                                    "criterion": "Turnover >= 50 lakh",
                                    "status": "met",
                                    "clause_ids": [self.ids["4.1"]],
                                    "note": "62 lakh >= 50 lakh",
                                },
                                {
                                    "criterion_id": "C2",
                                    "criterion": "ISO 9001",
                                    "status": "met",
                                    "clause_ids": [self.ids["4.2"]],
                                    "note": "Profile lists ISO 9001",
                                },
                            ]
                        }
                    )
                ],
            ), usage
        if ctx.purpose == "agent_verify":
            return _msg(
                "end_turn",
                [
                    _text(
                        {"supported": self.verify_ok, "reason": "ok" if self.verify_ok else "wrong"}
                    )
                ],
            ), usage
        if ctx.purpose == "agent_revise":
            return _msg(
                "end_turn",
                [
                    _text(
                        {
                            "findings": [
                                {
                                    "criterion_id": "C1",
                                    "criterion": "Turnover",
                                    "status": "met",
                                    "clause_ids": [self.ids["4.1"]],
                                    "note": "still met",
                                },
                                {
                                    "criterion_id": "C2",
                                    "criterion": "ISO 9001",
                                    "status": "met",
                                    "clause_ids": [self.ids["4.2"]],
                                    "note": "still met",
                                },
                            ]
                        }
                    )
                ],
            ), usage
        raise AssertionError(ctx.purpose)


async def _setup(sm: SM, portal_id: int) -> tuple[int, uuid.UUID, dict[str, int]]:
    org = uuid.uuid4()
    async with sm() as s, s.begin():
        tid = (
            await s.execute(
                text(
                    "INSERT INTO tenders (portal_id, tender_ref, title, pipeline_status, closes_at) "
                    "VALUES (:p, 'T', 'Lights', 'indexed', now() + interval '9 days') RETURNING id"
                ),
                {"p": portal_id},
            )
        ).scalar_one()
        did = (
            await s.execute(
                text(
                    "INSERT INTO tender_documents (tender_id, storage_key, sha256) "
                    "VALUES (:t, 'k', 'sha-agent') RETURNING id"
                ),
                {"t": tid},
            )
        ).scalar_one()
        ids = {}
        vecs = await embed([f"{sec}\n{body}" for _, sec, body in CLAUSES])
        for (no, sec, body), v in zip(CLAUSES, vecs, strict=True):
            ids[no] = (
                await s.execute(
                    text(
                        "INSERT INTO clauses (document_id, tender_id, clause_no, section, page_start, "
                        "page_end, text, embedding) VALUES (:d, :t, :no, :sec, 1, 1, :b, "
                        "CAST(:v AS vector)) RETURNING id"
                    ),
                    {"d": did, "t": tid, "no": no, "sec": sec, "b": body, "v": to_pgvector(v)},
                )
            ).scalar_one()
        await s.execute(
            text("INSERT INTO orgs (id, name) VALUES (:o, 'Acme Electricals')"), {"o": org}
        )
        await s.execute(
            text(
                "INSERT INTO company_profiles (org_id, version, annual_turnover_inr, is_msme, "
                "certifications, confirmed_at) VALUES (:o, 1, 6200000, true, '{ISO 9001}', now())"
            ),
            {"o": org},
        )
    return int(tid), org, ids


@pytest.mark.slow
async def test_full_run_plan_tool_loop_verify(sessionmaker: SM, portal_id: int) -> None:
    tid, org, ids = await _setup(sessionmaker, portal_id)
    fake = ScriptedClaude(ids)
    async with sessionmaker() as s:
        from core.profiles.store import get_confirmed_profile

        profile = await get_confirmed_profile(s, org)
        assert profile is not None
        result = await run_eligibility(s, fake, tid, org, profile)  # type: ignore[arg-type]

    assert result.report.verdict == "eligible" and not result.report.needs_review
    assert [f.status for f in result.report.findings] == ["met", "met"]
    assert result.plan is not None and result.plan.criteria[1].clause_ids == [ids["4.2"]]
    # compare_numeric ran in code and its result went back to the model.
    tool_result = json.loads(fake.tool_results[0]["content"])
    assert tool_result["satisfied"] is True and tool_result["actual"] == "6200000"
    assert fake.purposes.count("agent_verify") == 2


@pytest.mark.slow
async def test_unsupported_findings_become_unclear_and_need_review(
    sessionmaker: SM, portal_id: int
) -> None:
    tid, org, ids = await _setup(sessionmaker, portal_id)
    fake = ScriptedClaude(ids, verify_ok=False)
    async with sessionmaker() as s:
        from core.profiles.store import get_confirmed_profile

        profile = await get_confirmed_profile(s, org)
        assert profile is not None
        result = await run_eligibility(s, fake, tid, org, profile)  # type: ignore[arg-type]
    assert result.report.needs_review and result.report.verdict == "needs_review"
    assert {f.status for f in result.report.findings} == {"unclear"}
    assert "agent_revise" in fake.purposes  # one retry happened


@pytest.mark.slow
async def test_fit_check_job_writes_report_and_match(
    sessionmaker: SM, portal_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    tid, org, ids = await _setup(sessionmaker, portal_id)
    fake = ScriptedClaude(ids)
    monkeypatch.setattr(fit_check, "get_claude", lambda: fake)
    for _ in range(2):  # second run hits the cache: no new LLM calls
        async with sessionmaker() as s, s.begin():
            await fit_check.handle({"org_id": str(org), "tender_id": tid}, s)
    async with sessionmaker() as s:
        report = (await s.execute(text("SELECT verdict, findings FROM eligibility_reports"))).one()
        match = (await s.execute(text("SELECT stage, fit FROM matches"))).one()
    assert report.verdict == "eligible" and len(report.findings) == 2
    assert all(f["clause_ids"] for f in report.findings)
    assert (match.stage, match.fit) == ("agent_checked", "good")
    assert fake.purposes.count("agent_plan") == 1


def test_compute_verdict() -> None:
    def f(status: str) -> Finding:
        return Finding(
            criterion_id="x",
            criterion="x",
            status=status,  # type: ignore[arg-type]
            clause_ids=[1],
            note="",
        )

    assert compute_verdict([f("met"), f("exempt")], False) == "eligible"
    assert compute_verdict([f("met"), f("unclear")], False) == "possibly_eligible"
    assert compute_verdict([f("met"), f("not_met")], True) == "not_eligible"
    assert compute_verdict([f("met")], True) == "needs_review"
    assert compute_verdict([], False) == "needs_review"
