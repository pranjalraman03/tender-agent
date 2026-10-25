"""Eligibility agent: plan -> check -> verify -> report, with budgets.

- plan (fast model): list criteria from retrieved eligibility clauses, each citing clause ids.
- check (strong model, tool loop): assess every criterion against the confirmed profile.
- verify (fast model): each finding is checked against the text of the clauses it cites.
  Unsupported findings get one revision; if still unsupported they become "unclear" and the
  report is marked needs_review. Findings without citations are never accepted (rule 2).
- The verdict is computed in code from the findings.
Hitting the tool-call, token or time budget returns a partial report marked needs_review.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent.schemas import CheckResult, Finding, Plan, Report, Verdict, Verification
from core.agent.tools import TOOL_DEFS, AgentTools, ToolError
from core.agent.verifier import clause_texts, verify_all
from core.config import get_settings
from core.llm.claude import (
    UNTRUSTED_NOTE,
    CallContext,
    Claude,
    Effort,
    LLMOutputInvalid,
    Tier,
    Usage,
    strict_schema,
    tool_result_json,
    wrap_untrusted,
)
from core.profiles.store import profile_for_agent
from core.search.hybrid import search_clauses

log = structlog.get_logger()

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSIONS = {"plan": "plan_v1", "check": "check_v1", "verify": "verify_v1"}
PROMPTS = {step: (PROMPT_DIR / f"{v}.md").read_text() for step, v in PROMPT_VERSIONS.items()}

PLAN_QUERIES = [
    "eligibility criteria for bidders",
    "pre-qualification requirements",
    "minimum average annual financial turnover",
    "similar work experience completed works",
    "registration licence certificate required",
    "bid security earnest money deposit",
    "exemption for MSE startups",
]
MAX_PLAN_CLAUSES = 25


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    max_tool_calls: int
    max_tokens: int
    tool_calls: int = 0
    usage: Usage = field(default_factory=Usage)

    def add(self, usage: Usage) -> None:
        self.usage.add(usage)
        if self.usage.total_tokens > self.max_tokens:
            raise BudgetExceeded(f"token budget {self.max_tokens} reached")

    def tool_call(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool-call budget {self.max_tool_calls} reached")


@dataclass
class RunResult:
    report: Report
    usage: Usage
    trace_id: str
    prompt_versions: dict[str, str]
    plan: Plan | None


def compute_verdict(findings: list[Finding], needs_review: bool) -> Verdict:
    statuses = {f.status for f in findings}
    if "not_met" in statuses:
        return "not_eligible"
    if needs_review or not findings:
        return "needs_review"
    if statuses <= {"met", "exempt"}:
        return "eligible"
    return "possibly_eligible"


def _text(response: Any) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


async def _structured(
    claude: Claude,
    ctx: CallContext,
    budget: Budget,
    output: type[BaseModel],
    *,
    tier: Tier,
    system: str,
    messages: list[dict[str, Any]],
    effort: Effort = "low",
    tools: list[dict[str, Any]] | None = None,
) -> tuple[Any, list[dict[str, Any]], Any]:
    """One structured call with one repair retry. Returns (parsed, messages, response)."""
    schema = strict_schema(output)
    for attempt in range(2):
        response, usage = await claude.create(
            ctx,
            tier=tier,
            system=system,
            messages=messages,
            effort=effort,
            tools=tools,
            output_schema=schema,
        )
        budget.add(usage)
        try:
            return output.model_validate_json(_text(response)), messages, response
        except ValidationError as exc:
            if attempt == 1:
                raise LLMOutputInvalid(f"{ctx.purpose}: {exc}") from exc
            messages = [
                *messages,
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": f"Invalid output: {exc}. Reply with corrected JSON only.",
                },
            ]
    raise AssertionError("unreachable")


async def _plan(
    session: AsyncSession, claude: Claude, ctx: CallContext, budget: Budget, tender_id: int
) -> tuple[Plan, set[int]]:
    candidates: dict[int, Any] = {}
    for q in PLAN_QUERIES:
        for h in await search_clauses(session, tender_id, q, k=5):
            candidates.setdefault(h.clause_id, h)
    hits = list(candidates.values())[:MAX_PLAN_CLAUSES]
    if not hits:
        return Plan(criteria=[]), set()
    clause_block = "\n\n".join(
        f"[clause_id={h.clause_id}] clause {h.clause_no or '-'} | section: {h.section or '-'} "
        f"| pages {h.page_start}-{h.page_end}\n{h.text}"
        for h in hits
    )
    plan, _, _ = await _structured(
        claude,
        ctx,
        budget,
        Plan,
        tier="fast",
        system=PROMPTS["plan"] + "\n\n" + UNTRUSTED_NOTE,
        messages=[{"role": "user", "content": wrap_untrusted("tender_clauses", clause_block)}],
    )
    valid_ids = set(candidates)
    criteria = []
    for c in plan.criteria:
        c.clause_ids = [i for i in c.clause_ids if i in valid_ids]
        if c.clause_ids:  # no citation, no claim
            criteria.append(c)
    return Plan(criteria=criteria), valid_ids


async def _check(
    tools: AgentTools, claude: Claude, ctx: CallContext, budget: Budget, plan: Plan
) -> list[Finding]:
    criteria_json = json.dumps([c.model_dump() for c in plan.criteria], ensure_ascii=False)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"tender_id: {tools.tender_id}\norg_id: {tools.org_id}\n\n"
            f"Criteria to assess:\n{criteria_json}",
        }
    ]
    schema = strict_schema(CheckResult)
    system = PROMPTS["check"] + "\n\n" + UNTRUSTED_NOTE
    repaired = False
    while True:
        response, usage = await claude.create(
            ctx,
            tier="strong",
            system=system,
            messages=messages,
            effort="high",
            tools=TOOL_DEFS,
            output_schema=schema,
            max_tokens=32000,
        )
        budget.add(usage)
        # Append the assistant turn unchanged (thinking blocks included): append-only history.
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                budget.tool_call()
                try:
                    out = await tools.run(block.name, dict(block.input))
                    content = tool_result_json(out)
                    # Tender/website text returned by tools is data, not instructions.
                    if block.name in ("search_clauses", "get_clause", "check_exemptions"):
                        content = wrap_untrusted(block.name, content)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": content}
                    )
                except (ToolError, KeyError, ValueError) as exc:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {exc}",
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": results})
            continue
        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason == "max_tokens":
            raise BudgetExceeded("response hit max_tokens")
        try:
            return CheckResult.model_validate_json(_text(response)).findings
        except ValidationError as exc:
            if repaired:
                raise LLMOutputInvalid(f"check: {exc}") from exc
            repaired = True
            messages.append(
                {
                    "role": "user",
                    "content": f"Invalid output: {exc}. Reply with the corrected JSON only.",
                }
            )


async def _revise(
    session: AsyncSession,
    claude: Claude,
    ctx: CallContext,
    budget: Budget,
    tender_id: int,
    rejected: list[tuple[Finding, Verification]],
    profile: dict[str, Any],
) -> list[Finding]:
    ids = sorted({i for f, _ in rejected for i in f.clause_ids})
    clauses = await clause_texts(session, tender_id, ids)
    problems = "\n\n".join(f"{f.model_dump_json()}\nVerifier: {v.reason}" for f, v in rejected)
    user = (
        "These findings failed verification. Revise each one so it is supported by the cited "
        "clause text and consistent with the company facts; change the status to 'unclear' if "
        f"the clauses don't settle it.\n\n{problems}\n\nCompany facts:\n"
        f"{json.dumps(profile, default=str, ensure_ascii=False)}\n\n"
        + wrap_untrusted("cited_clauses", "\n\n".join(clauses.values()))
    )
    result, _, _ = await _structured(
        claude,
        ctx,
        budget,
        CheckResult,
        tier="strong",
        effort="medium",
        system=PROMPTS["check"] + "\n\n" + UNTRUSTED_NOTE,
        messages=[{"role": "user", "content": user}],
    )
    assert isinstance(result, CheckResult)
    return result.findings


def _partial(plan: Plan | None, reason: str) -> list[Finding]:
    if plan is None:
        return []
    return [
        Finding(
            criterion_id=c.id,
            criterion=c.description,
            status="unclear",
            clause_ids=c.clause_ids,
            note=f"Not assessed: {reason}",
        )
        for c in plan.criteria
    ]


async def run_eligibility(
    session: AsyncSession,
    claude: Claude,
    tender_id: int,
    org_id: uuid.UUID,
    profile: dict[str, Any],
    trace_id: str | None = None,
) -> RunResult:
    settings = get_settings()
    trace_id = trace_id or uuid.uuid4().hex
    budget = Budget(settings.agent_max_tool_calls, settings.agent_max_tokens)
    agent_profile = profile_for_agent(profile)
    tools = AgentTools(session, tender_id, org_id, profile)
    started = time.monotonic()
    plan: Plan | None = None
    findings: list[Finding] = []
    reasons: list[str] = []

    def ctx(step: str) -> CallContext:
        return CallContext(purpose=f"agent_{step}", org_id=org_id, trace_id=trace_id)

    try:
        async with asyncio.timeout(settings.agent_timeout_s):
            plan, _ = await _plan(session, claude, ctx("plan"), budget, tender_id)
            if not plan.criteria:
                reasons.append("no eligibility criteria found in the tender clauses")
            else:
                findings = await _check(tools, claude, ctx("check"), budget, plan)
                findings = _reconcile(plan, findings)
                verdicts = await verify_all(
                    session,
                    claude,
                    ctx("verify"),
                    budget,
                    tender_id,
                    findings,
                    agent_profile,
                    _structured,
                    PROMPTS["verify"],
                )
                rejected = [
                    (f, v) for f, v in zip(findings, verdicts, strict=True) if not v.supported
                ]
                if rejected:
                    revised = {
                        f.criterion_id: f
                        for f in await _revise(
                            session,
                            claude,
                            ctx("revise"),
                            budget,
                            tender_id,
                            rejected,
                            agent_profile,
                        )
                    }
                    retry = [revised.get(f.criterion_id, f) for f, _ in rejected]
                    second = await verify_all(
                        session,
                        claude,
                        ctx("verify"),
                        budget,
                        tender_id,
                        retry,
                        agent_profile,
                        _structured,
                        PROMPTS["verify"],
                    )
                    fixed = {f.criterion_id: (f, v) for f, v in zip(retry, second, strict=True)}
                    out = []
                    for f in findings:
                        if f.criterion_id not in fixed:
                            out.append(f)
                            continue
                        nf, v = fixed[f.criterion_id]
                        if v.supported:
                            out.append(nf)
                        else:
                            reasons.append(f"{f.criterion_id}: {v.reason}")
                            out.append(
                                nf.model_copy(
                                    update={
                                        "status": "unclear",
                                        "note": f"Needs review: {v.reason}",
                                    }
                                )
                            )
                    findings = out
    except (TimeoutError, BudgetExceeded) as exc:
        reason = "time budget reached" if isinstance(exc, TimeoutError) else str(exc)
        reasons.append(reason)
        done = {f.criterion_id for f in findings}
        findings = findings + [f for f in _partial(plan, reason) if f.criterion_id not in done]

    # Rule 2, enforced last: only citations of this tender's clauses count, and a finding
    # without any is never reported as a claim.
    cited = sorted({i for f in findings for i in f.clause_ids})
    valid = set(await clause_texts(session, tender_id, cited)) if cited else set()
    findings = [
        f.model_copy(update={"clause_ids": [i for i in f.clause_ids if i in valid]})
        for f in findings
    ]
    findings = [f for f in findings if f.clause_ids]
    needs_review = bool(reasons)
    report = Report(
        verdict=compute_verdict(findings, needs_review),
        findings=findings,
        needs_review=needs_review,
        review_reasons=reasons,
    )
    log.info(
        "eligibility_done",
        tender_id=tender_id,
        org_id=str(org_id),
        trace_id=trace_id,
        verdict=report.verdict,
        findings=len(findings),
        tool_calls=budget.tool_calls,
        cost_usd=str(budget.usage.cost_usd),
        seconds=round(time.monotonic() - started, 1),
    )
    return RunResult(report, budget.usage, trace_id, dict(PROMPT_VERSIONS), plan)


def _reconcile(plan: Plan, findings: list[Finding]) -> list[Finding]:
    """One finding per planned criterion, in plan order; missing ones become 'unclear'."""
    by_id = {f.criterion_id: f for f in findings}
    out = []
    for c in plan.criteria:
        f = by_id.get(c.id)
        if f is None:
            out.append(
                Finding(
                    criterion_id=c.id,
                    criterion=c.description,
                    status="unclear",
                    clause_ids=c.clause_ids,
                    note="Not assessed by the checker.",
                )
            )
        else:
            out.append(f.model_copy(update={"clause_ids": f.clause_ids or c.clause_ids}))
    return out
