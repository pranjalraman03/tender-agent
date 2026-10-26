"""Run the golden set, write an eval_runs row, exit non-zero on regression vs main.

    uv run python evals/run_evals.py              # retrieval metrics (no API key needed)
    uv run python evals/run_evals.py --agent      # + verdict accuracy, criterion F1, cost
    uv run python evals/run_evals.py --agent --judge   # + LLM-judged citation precision

Each run builds a throwaway `<db>_eval` database: migrate, seed, ingest + parse + embed
every case's PDFs, then score. Synthetic cases (format/smoke checks) are reported
separately and never count towards the headline metrics while real cases exist.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.agent.loop import run_eligibility
from core.config import get_settings
from core.db.session import set_system_context, system_transaction
from core.documents import ingest_document
from core.jobs import parse
from core.jobs.index import embed_missing_clauses
from core.llm.claude import UNTRUSTED_NOTE, CallContext, Claude, wrap_untrusted
from core.observability import configure_logging
from core.reference.industries import seed_reference_data
from core.search.hybrid import search_clauses
from core.storage import get_storage
from evals.metrics import criterion_scores, p50_p95, recall_at_k, regressions
from evals.schema import GoldCase

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "golden"
JUDGE_PROMPT = (ROOT / "judge_v1.md").read_text()


class Judgement(BaseModel):
    supported: bool


def load_cases(pattern: str) -> list[GoldCase]:
    return [
        GoldCase.model_validate_json(p.read_text())
        for p in sorted(GOLDEN.glob(pattern))
        if p.is_file()
    ]


def git(*args: str) -> str | None:
    try:
        # Fixed git subcommands from this file only; no user input reaches the command.
        out = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


async def make_eval_db() -> async_sessionmaker[AsyncSession]:
    base = make_url(get_settings().database_url)
    url = base.set(database=f"{base.database}_eval").render_as_string(hide_password=False)
    admin = create_async_engine(get_settings().database_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        name = make_url(url).database
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()
    cfg = Config(str(ROOT.parent / "alembic.ini"))
    cfg.attributes["database_url"] = url
    await asyncio.to_thread(command.upgrade, cfg, "head")
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


async def load_case(sm: async_sessionmaker[AsyncSession], case: GoldCase) -> tuple[int, uuid.UUID]:
    org_id = uuid.uuid4()
    async with sm() as s, s.begin():
        await set_system_context(s)
        portal_id = (
            await s.execute(
                text(
                    "INSERT INTO portals (name, base_url) VALUES ('eval', 'https://example.org') "
                    "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                )
            )
        ).scalar_one()
        tender_id = (
            await s.execute(
                text("""
            INSERT INTO tenders (portal_id, tender_ref, title, org_name, portal_fields,
                                 closes_at, pipeline_status)
            VALUES (:p, :ref, :title, :org, CAST(:fields AS jsonb), now() + interval '30 days',
                    'discovered') RETURNING id"""),
                {
                    "p": portal_id,
                    "ref": case.name,
                    "title": case.tender.get("title", case.name),
                    "org": case.tender.get("org_name"),
                    "fields": json.dumps(case.tender.get("portal_fields", {})),
                },
            )
        ).scalar_one()
        for rel in case.pdfs:
            path = GOLDEN / "pdfs" / rel
            await ingest_document(s, get_storage(), tender_id, path.name, path.read_bytes())
        await s.execute(
            text("INSERT INTO orgs (id, name) VALUES (:o, :n)"),
            {"o": org_id, "n": case.profile.get("company_name", "Eval Co")},
        )
        p = case.profile
        await s.execute(
            text("""
                INSERT INTO company_profiles (org_id, version, confirmed_at, description,
                    industries, nic_codes, msme_category, states, annual_turnover_inr,
                    years_in_business, is_msme, certifications, past_projects)
                VALUES (:org, 1, now(), :description, :industries, :nic_codes, :msme_category,
                        :states, :turnover, :years, :is_msme, :certifications,
                        CAST(:past_projects AS jsonb))
            """),
            {
                "org": org_id,
                "description": p.get("description"),
                "industries": p.get("industries", []),
                "nic_codes": p.get("nic_codes", []),
                "msme_category": p.get("msme_category"),
                "states": p.get("states", []),
                "turnover": p.get("annual_turnover_inr"),
                "years": p.get("years_in_business"),
                "is_msme": p.get("is_msme"),
                "certifications": p.get("certifications", []),
                "past_projects": json.dumps(p.get("past_projects", [])),
            },
        )
        docs = (
            (
                await s.execute(
                    text("SELECT id FROM tender_documents WHERE tender_id = :t"), {"t": tender_id}
                )
            )
            .scalars()
            .all()
        )
        for doc_id in docs:
            await parse.handle({"document_id": doc_id}, s)
        await embed_missing_clauses(s, tender_id)
        # Mark live so the agent's tools treat it like a real tender.
        await s.execute(
            text("UPDATE tenders SET pipeline_status = 'indexed', industries = :ind WHERE id = :t"),
            {"t": tender_id, "ind": case.tender.get("industries", [])},
        )
    return int(tender_id), org_id


async def judge_citations(claude: Claude, findings: list[dict[str, Any]]) -> list[bool]:
    async def one(f: dict[str, Any]) -> bool:
        user = f"Finding: {f['criterion']} -> {f['status']}. {f['note']}\n\n" + wrap_untrusted(
            "cited_clauses", "\n\n".join(f["clause_texts"])
        )
        result, _ = await claude.json(
            CallContext(purpose="eval_judge"),
            Judgement,
            tier="fast",
            system=JUDGE_PROMPT + "\n\n" + UNTRUSTED_NOTE,
            user=user,
        )
        return result.supported

    return list(await asyncio.gather(*(one(f) for f in findings)))


async def run(args: argparse.Namespace) -> int:
    configure_logging(json_logs=False)
    cases = load_cases(args.cases)
    if not cases:
        print(f"no cases match {GOLDEN / args.cases}")  # noqa: T201
        return 1
    real = [c for c in cases if not c.synthetic]
    scored = real or cases
    if args.agent and not get_settings().llm_configured:
        print("--agent needs ANTHROPIC_API_KEY")  # noqa: T201
        return 1

    sm = await make_eval_db()
    async with sm() as s, s.begin():
        await set_system_context(s)
        await seed_reference_data(s)

    claude = Claude() if args.agent else None
    retrieved: list[list[str]] = []
    gold_all = []
    correct = 0
    f1s: list[float] = []
    costs: list[float] = []
    latencies: list[float] = []
    judged: list[bool] = []
    per_case = []

    for case in scored:
        tender_id, org_id = await load_case(sm, case)
        async with sm() as s:
            await set_system_context(s)
            for g in case.criteria:
                hits = await search_clauses(s, tender_id, g.query or g.description, k=10)
                retrieved.append([h.text for h in hits])
                gold_all.append(g)
        row: dict[str, Any] = {"case": case.name}
        if claude is not None:
            async with sm() as s:
                await set_system_context(s)
                profile = (
                    (
                        await s.execute(
                            text(
                                "SELECT o.name AS company_name, p.* FROM company_profiles p "
                                "JOIN orgs o ON o.id = p.org_id WHERE p.org_id = :o"
                            ),
                            {"o": org_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                started = time.monotonic()
                try:
                    result = await run_eligibility(s, claude, tender_id, org_id, dict(profile))
                except Exception as exc:  # one failing case must not abort the whole run
                    latencies.append(time.monotonic() - started)
                    f1s.append(0.0)
                    costs.append(0.0)
                    row.update(verdict="error", gold_verdict=case.verdict, error=repr(exc)[:300])
                    per_case.append(row)
                    continue
                latencies.append(time.monotonic() - started)
                ids = sorted({i for f in result.report.findings for i in f.clause_ids})
                texts: dict[int, str] = dict(
                    (
                        await s.execute(
                            text("SELECT id, text FROM clauses WHERE id = ANY(:ids)"),
                            {"ids": ids},
                        )
                    )
                    .tuples()
                    .all()
                )
            predicted = [
                {
                    "criterion": f.criterion,
                    "status": f.status,
                    "note": f.note,
                    "clause_texts": [texts[i] for i in f.clause_ids if i in texts],
                }
                for f in result.report.findings
            ]
            _, _, f1 = criterion_scores(predicted, case.criteria)
            f1s.append(f1)
            correct += result.report.verdict == case.verdict
            costs.append(float(result.usage.cost_usd))
            row.update(
                verdict=result.report.verdict,
                gold_verdict=case.verdict,
                criterion_f1=round(f1, 3),
                cost_usd=round(costs[-1], 4),
            )
            if args.judge and predicted:
                judged.extend(await judge_citations(claude, predicted))
        per_case.append(row)

    metrics: dict[str, Any] = {
        "cases": len(scored),
        "synthetic_only": not real,
        "retrieval_recall_at_5": recall_at_k(retrieved, gold_all, 5),
        "retrieval_recall_at_10": recall_at_k(retrieved, gold_all, 10),
    }
    if claude is not None:
        p50, p95 = p50_p95(latencies)
        c50, c95 = p50_p95(costs)
        metrics.update(
            verdict_accuracy=correct / len(scored),
            criterion_f1=sum(f1s) / len(f1s),
            latency_s_p50=p50,
            latency_s_p95=p95,
            cost_usd_p50=c50,
            cost_usd_p95=c95,
        )
        if judged:
            metrics["citation_precision"] = sum(judged) / len(judged)

    branch, sha = git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "--short", "HEAD")
    async with system_transaction() as s:
        baseline = (
            await s.execute(
                text(
                    "SELECT metrics FROM eval_runs WHERE branch = 'main' "
                    "AND (metrics->>'synthetic_only')::boolean = :syn ORDER BY id DESC LIMIT 1"
                ),
                {"syn": not real},
            )
        ).scalar_one_or_none()
        await s.execute(
            text(
                "INSERT INTO eval_runs (git_sha, branch, metrics) "
                "VALUES (:sha, :branch, CAST(:m AS jsonb))"
            ),
            {"sha": sha, "branch": branch, "m": json.dumps({**metrics, "per_case": per_case})},
        )

    print(json.dumps({**metrics, "per_case": per_case}, indent=2))  # noqa: T201
    if not real:
        print(
            "\nNOTE: only synthetic cases ran; these numbers are smoke checks, "  # noqa: T201
            "not quality measurements. Label real tenders with evals/label_tool.py."
        )
    if baseline:
        bad = regressions(metrics, baseline)
        for line in bad:
            print(f"REGRESSION {line}")  # noqa: T201
        if bad and not args.no_fail:
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", action="store_true", help="run the eligibility agent")
    parser.add_argument("--judge", action="store_true", help="LLM-judge citation precision")
    parser.add_argument("--cases", default="*.json", help="glob under evals/golden/")
    parser.add_argument("--no-fail", action="store_true", help="report regressions, exit 0")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
