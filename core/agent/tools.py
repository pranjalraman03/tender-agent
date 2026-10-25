"""Read-only tools for the eligibility agent, with their JSON schemas.

Every tool is bound to one (tender, org) run: ids the model passes are checked against the
bound ones, so the model can never read another tender's clauses or another org's profile.
No tool writes data, sends anything, or fetches URLs (CLAUDE.md rule 7).
"""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.agent.numeric import AmountParseError, compare
from core.profiles.store import profile_for_agent
from core.search.hybrid import search_clauses

MAX_CLAUSE_CHARS = 2500

EXEMPTION_QUERIES = [
    "exemption for micro and small enterprises MSE Udyam NSIC",
    "EMD exemption bid security waiver",
    "relaxation of prior turnover and prior experience for startups and MSEs",
    "purchase preference for MSE",
]


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "search_clauses",
        "description": "Hybrid search over this tender's clauses. Returns the best matching "
        "clauses with ids, clause numbers, sections and pages.",
        "strict": True,
        "input_schema": _schema(
            {
                "tender_id": {"type": "integer"},
                "query": {"type": "string", "description": "What to look for, in plain words"},
                "section": {
                    "type": ["string", "null"],
                    "description": "Optional substring of the section name to filter by",
                },
            }
        ),
    },
    {
        "name": "get_clause",
        "description": "Full text of one clause of this tender by clause id.",
        "strict": True,
        "input_schema": _schema({"clause_id": {"type": "integer"}}),
    },
    {
        "name": "get_tender_fields",
        "description": "Structured fields of the tender: title, buyer, value, EMD, deadline, "
        "state, industries, and raw portal fields.",
        "strict": True,
        "input_schema": _schema({"tender_id": {"type": "integer"}}),
    },
    {
        "name": "get_profile",
        "description": "The company's confirmed profile: turnover, years in business, MSME "
        "status, certifications, past projects, states, industries.",
        "strict": True,
        "input_schema": _schema({"org_id": {"type": "string"}}),
    },
    {
        "name": "compare_numeric",
        "description": "Compare a requirement with the company's value in code. Accepts "
        "amounts as written (e.g. '50 lakh', 'Rs. 1.5 crore', '27,69,088'). "
        "Use this for every numeric comparison; do not compute yourself.",
        "strict": True,
        "input_schema": _schema(
            {
                "requirement": {"type": "string"},
                "actual": {"type": "string"},
                "rule": {"type": "string", "enum": [">=", ">", "<=", "<", "=="]},
            }
        ),
    },
    {
        "name": "check_exemptions",
        "description": "Find clauses that exempt or relax requirements for MSEs / startups "
        "(EMD waiver, turnover or experience relaxation, purchase preference), "
        "together with the company's MSME status.",
        "strict": True,
        "input_schema": _schema({"tender_id": {"type": "integer"}}),
    },
]


class ToolError(Exception):
    pass


class AgentTools:
    def __init__(
        self, session: AsyncSession, tender_id: int, org_id: uuid.UUID, profile: dict[str, Any]
    ) -> None:
        self.session = session
        self.tender_id = tender_id
        self.org_id = org_id
        self.profile = profile
        self.seen_clause_ids: set[int] = set()

    def _check_tender(self, tender_id: int) -> None:
        if tender_id != self.tender_id:
            raise ToolError(f"only tender {self.tender_id} is available in this run")

    async def run(self, name: str, args: dict[str, Any]) -> Any:
        if name == "search_clauses":
            self._check_tender(int(args["tender_id"]))
            hits = await search_clauses(
                self.session,
                self.tender_id,
                str(args["query"]),
                k=6,
                section=args.get("section") or None,
            )
            self.seen_clause_ids.update(h.clause_id for h in hits)
            return [
                {
                    "clause_id": h.clause_id,
                    "clause_no": h.clause_no,
                    "section": h.section,
                    "pages": f"{h.page_start}-{h.page_end}",
                    "text": h.text[:MAX_CLAUSE_CHARS],
                }
                for h in hits
            ]
        if name == "get_clause":
            row = (
                await self.session.execute(
                    text(
                        "SELECT id, clause_no, section, page_start, page_end, text FROM clauses "
                        "WHERE id = :id AND tender_id = :t"
                    ),
                    {"id": int(args["clause_id"]), "t": self.tender_id},
                )
            ).one_or_none()
            if row is None:
                raise ToolError("no such clause in this tender")
            self.seen_clause_ids.add(row.id)
            return {
                "clause_id": row.id,
                "clause_no": row.clause_no,
                "section": row.section,
                "pages": f"{row.page_start}-{row.page_end}",
                "text": row.text,
            }
        if name == "get_tender_fields":
            self._check_tender(int(args["tender_id"]))
            fields = (
                (
                    await self.session.execute(
                        text(
                            "SELECT title, org_name, value_inr, emd_inr, closes_at, work_state, "
                            "is_central, industries, summary, portal_fields FROM tenders "
                            "WHERE id = :t"
                        ),
                        {"t": self.tender_id},
                    )
                )
                .mappings()
                .one()
            )
            return {
                k: (str(v) if k in ("value_inr", "emd_inr", "closes_at") and v is not None else v)
                for k, v in fields.items()
            }
        if name == "get_profile":
            if str(args["org_id"]) != str(self.org_id):
                raise ToolError("only the current company's profile is available")
            return profile_for_agent(self.profile)
        if name == "compare_numeric":
            try:
                return compare(str(args["requirement"]), str(args["actual"]), args["rule"])
            except AmountParseError as exc:
                raise ToolError(str(exc)) from exc
        if name == "check_exemptions":
            self._check_tender(int(args["tender_id"]))
            found: dict[int, dict[str, Any]] = {}
            for q in EXEMPTION_QUERIES:
                for h in await search_clauses(self.session, self.tender_id, q, k=3):
                    found[h.clause_id] = {
                        "clause_id": h.clause_id,
                        "clause_no": h.clause_no,
                        "pages": f"{h.page_start}-{h.page_end}",
                        "text": h.text[:MAX_CLAUSE_CHARS],
                    }
            self.seen_clause_ids.update(found)
            return {
                "company": {
                    "is_msme": self.profile.get("is_msme"),
                    "msme_category": self.profile.get("msme_category"),
                    "certifications": self.profile.get("certifications"),
                },
                "candidate_clauses": list(found.values()),
            }
        raise ToolError(f"unknown tool {name}")
