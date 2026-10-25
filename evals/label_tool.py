"""Interactive CLI to create a golden case from real tender PDFs.

    uv run python evals/label_tool.py --name dda_930816_acme \\
        --pdf evals/golden/pdfs/dda_930816/nit.pdf --profile path/to/profile.json [--suggest]

1. Parses the PDFs exactly like the pipeline (same extractor and chunker).
2. Lists clauses that look eligibility-related, numbered for reference.
3. With --suggest (needs ANTHROPIC_API_KEY), pre-fills criteria with the fast model; you
   accept, edit or drop each one. Otherwise you enter criteria by hand.
4. For each criterion you pick the clause(s) that state it; a snippet of each becomes the
   gold evidence. Writes evals/golden/<name>.json.
The profile JSON uses company_profiles field names (see evals/golden/syn_*.json).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from core.agent.schemas import Plan
from core.config import get_settings
from core.llm.claude import UNTRUSTED_NOTE, CallContext, Claude, wrap_untrusted
from core.parsing.chunker import Chunk, chunk_pages
from core.parsing.pdf import extract_pdf
from evals.schema import GoldCase, GoldCriterion

GOLDEN = Path(__file__).resolve().parent / "golden"
KEYWORDS = (
    "eligib",
    "qualif",
    "turnover",
    "experience",
    "similar work",
    "registration",
    "registered",
    "licen",
    "certif",
    "iso",
    "emd",
    "earnest",
    "exempt",
    "msme",
    "mse",
    "startup",
    "solvency",
    "net worth",
    "blacklist",
)
STATUSES = ("met", "not_met", "unclear", "exempt")
VERDICTS = ("eligible", "possibly_eligible", "not_eligible", "needs_review")


def ask(prompt: str, choices: tuple[str, ...] | None = None, default: str | None = None) -> str:
    hint = f" [{'/'.join(choices)}]" if choices else ""
    hint += f" (default: {default})" if default else ""
    while True:
        value = input(f"{prompt}{hint}: ").strip() or (default or "")
        if not choices or value in choices:
            return value
        print(f"  choose one of: {', '.join(choices)}")


def snippet(chunk: Chunk) -> str:
    # The first sentence-ish of the clause, without the clause number.
    body = " ".join(chunk.text.split())
    return body[:140]


async def suggest(chunks: list[tuple[int, Chunk]]) -> list[dict[str, Any]]:
    block = "\n\n".join(
        f"[clause_id={i}] clause {c.clause_no or '-'} | {c.section or '-'}\n{c.text}"
        for i, c in chunks
    )
    prompt = (Path(__file__).resolve().parents[1] / "core/agent/prompts/plan_v1.md").read_text()
    plan, _ = await Claude().json(
        CallContext(purpose="label_suggest"),
        Plan,
        tier="fast",
        system=prompt + "\n\n" + UNTRUSTED_NOTE,
        user=wrap_untrusted("tender_clauses", block),
    )
    return [c.model_dump() for c in plan.criteria]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--pdf", action="append", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--suggest", action="store_true")
    args = parser.parse_args()

    out_path = GOLDEN / f"{args.name}.json"
    if out_path.exists() and ask(f"{out_path.name} exists. Overwrite?", ("y", "n"), "n") != "y":
        sys.exit(0)
    profile = json.loads(Path(args.profile).read_text())

    all_chunks: list[Chunk] = []
    for pdf in args.pdf:
        extracted = await extract_pdf(Path(pdf).read_bytes())
        all_chunks.extend(chunk_pages(extracted.pages))
    relevant = [
        (i, c)
        for i, c in enumerate(all_chunks)
        if any(k in f"{c.section or ''} {c.text}".lower() for k in KEYWORDS)
    ]
    print(f"\n{len(all_chunks)} clauses parsed; {len(relevant)} look eligibility-related:\n")
    for i, c in relevant:
        print(f"[{i}] clause {c.clause_no or '-'} | {c.section or '-'} | p.{c.page_start}")
        print(f"     {snippet(c)}")

    drafts: list[dict[str, Any]] = []
    if args.suggest:
        if not get_settings().llm_configured:
            print("--suggest needs ANTHROPIC_API_KEY; continuing without suggestions")
        else:
            drafts = await suggest(relevant)

    criteria: list[GoldCriterion] = []
    print("\nCriteria. For each: description, the gold status for THIS profile, clause numbers.")
    for d in drafts:
        print(f"\nSuggested: {d['description']}  (clauses {d['clause_ids']})")
        action = ask("keep / edit / drop", ("k", "e", "d"), "k")
        if action == "d":
            continue
        desc = d["description"] if action == "k" else ask("description", default=d["description"])
        ids = [
            int(x)
            for x in ask("clause numbers", default=",".join(map(str, d["clause_ids"]))).split(",")
            if x.strip()
        ]
        status = ask("status", STATUSES)
        criteria.append(
            GoldCriterion(
                description=desc,
                status=status,
                evidence=[snippet(all_chunks[i]) for i in ids],
            )
        )
    while ask("\nAdd a criterion?", ("y", "n"), "n" if criteria else "y") == "y":
        desc = ask("description")
        ids = [int(x) for x in ask("clause numbers (comma-separated)").split(",") if x.strip()]
        status = ask("status", STATUSES)
        criteria.append(
            GoldCriterion(
                description=desc,
                status=status,
                evidence=[snippet(all_chunks[i]) for i in ids],
            )
        )

    pdf_dir = GOLDEN / "pdfs"
    case = GoldCase(
        name=args.name,
        pdfs=[str(Path(p).resolve().relative_to(pdf_dir.resolve())) for p in args.pdf],
        tender={
            "title": ask("tender title"),
            "org_name": ask("buyer organisation"),
            "industries": [
                s.strip() for s in ask("industry slugs (comma-separated)").split(",") if s.strip()
            ],
        },
        profile=profile,
        verdict=ask("overall verdict", VERDICTS),
        criteria=criteria,
        notes=ask("notes (why this verdict)", default=""),
    )
    out_path.write_text(case.model_dump_json(indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
