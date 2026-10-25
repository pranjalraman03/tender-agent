"""Verifier: checks each finding against the text of the clauses it cites (fast model).
A finding that cites nothing from this tender is rejected without a model call."""

import asyncio
import json
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent.schemas import Finding, Verification
from core.llm.claude import UNTRUSTED_NOTE, CallContext, Claude, wrap_untrusted


class StructuredCall(Protocol):
    async def __call__(
        self,
        claude: Claude,
        ctx: CallContext,
        budget: Any,
        output: Any,
        *,
        tier: Any,
        system: str,
        messages: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any]: ...


async def clause_texts(session: AsyncSession, tender_id: int, ids: list[int]) -> dict[int, str]:
    rows = (
        await session.execute(
            text(
                "SELECT id, clause_no, page_start, text FROM clauses "
                "WHERE tender_id = :t AND id = ANY(:ids)"
            ),
            {"t": tender_id, "ids": ids},
        )
    ).all()
    return {
        r.id: f"[clause_id={r.id}] clause {r.clause_no or '-'} (p.{r.page_start})\n{r.text}"
        for r in rows
    }


async def verify_finding(
    claude: Claude,
    ctx: CallContext,
    budget: Any,
    finding: Finding,
    clauses: dict[int, str],
    profile: dict[str, Any],
    structured: StructuredCall,
    prompt: str,
) -> Verification:
    cited = [clauses[i] for i in finding.clause_ids if i in clauses]
    if not cited:
        return Verification(supported=False, reason="finding cites no clause of this tender")
    user = (
        f"Finding:\n{finding.model_dump_json()}\n\nCompany facts:\n"
        f"{json.dumps(profile, default=str, ensure_ascii=False)}\n\n"
        + wrap_untrusted("cited_clauses", "\n\n".join(cited))
    )
    result, _, _ = await structured(
        claude,
        ctx,
        budget,
        Verification,
        tier="fast",
        system=prompt + "\n\n" + UNTRUSTED_NOTE,
        messages=[{"role": "user", "content": user}],
    )
    assert isinstance(result, Verification)
    return result


async def verify_all(
    session: AsyncSession,
    claude: Claude,
    ctx: CallContext,
    budget: Any,
    tender_id: int,
    findings: list[Finding],
    profile: dict[str, Any],
    structured: StructuredCall,
    prompt: str,
) -> list[Verification]:
    ids = sorted({i for f in findings for i in f.clause_ids})
    clauses = await clause_texts(session, tender_id, ids)
    return list(
        await asyncio.gather(
            *(
                verify_finding(claude, ctx, budget, f, clauses, profile, structured, prompt)
                for f in findings
            )
        )
    )
