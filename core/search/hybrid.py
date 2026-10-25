"""Hybrid clause search within one tender: vector (cosine) + full-text, fused with
reciprocal rank fusion, then reranked.

    score_rrf(clause) = sum over result lists of 1 / (RRF_K + rank)
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.embeddings import embed_one, rerank, to_pgvector

RRF_K = 60
CANDIDATES = 30
RERANK_TOP = 20


@dataclass(frozen=True)
class ClauseHit:
    clause_id: int
    clause_no: str | None
    section: str | None
    page_start: int
    page_end: int
    document_id: int
    text: str
    score: float


def rrf(*ranked_lists: list[int], k: int = RRF_K) -> list[tuple[int, float]]:
    """Fuse ranked id lists. Returns (id, score) sorted best first; ties keep first-seen order."""
    scores: dict[int, float] = {}
    for ids in ranked_lists:
        for rank, clause_id in enumerate(ids, start=1):
            scores[clause_id] = scores.get(clause_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


async def search_clauses(
    session: AsyncSession,
    tender_id: int,
    query: str,
    *,
    k: int = 8,
    section: str | None = None,
    use_rerank: bool = True,
) -> list[ClauseHit]:
    qvec = to_pgvector(await embed_one(query, "query"))
    params = {"t": tender_id, "q": query, "v": qvec, "n": CANDIDATES, "section": section}

    vector_ids = list(
        (
            await session.execute(
                text("""
                    SELECT c.id FROM clauses c
                    WHERE c.tender_id = :t AND c.embedding IS NOT NULL
                      AND (CAST(:section AS text) IS NULL
                           OR c.section ILIKE '%' || :section || '%')
                    ORDER BY c.embedding <=> CAST(:v AS vector)
                    LIMIT :n
                """),
                params,
            )
        ).scalars()
    )
    fts_ids = list(
        (
            await session.execute(
                text("""
                    SELECT c.id FROM clauses c,
                         websearch_to_tsquery('english', :q) AS query
                    WHERE c.tender_id = :t AND c.tsv @@ query
                      AND (CAST(:section AS text) IS NULL
                           OR c.section ILIKE '%' || :section || '%')
                    ORDER BY ts_rank(c.tsv, query) DESC
                    LIMIT :n
                """),
                params,
            )
        ).scalars()
    )
    fused = rrf(vector_ids, fts_ids)[:RERANK_TOP]
    if not fused:
        return []

    rows = {
        r.id: r
        for r in (
            await session.execute(
                text("""
                    SELECT id, clause_no, section, page_start, page_end, document_id, text
                    FROM clauses WHERE id = ANY(:ids)
                """),
                {"ids": [cid for cid, _ in fused]},
            )
        ).all()
    }
    hits = [
        ClauseHit(
            cid,
            rows[cid].clause_no,
            rows[cid].section,
            rows[cid].page_start,
            rows[cid].page_end,
            rows[cid].document_id,
            rows[cid].text,
            score,
        )
        for cid, score in fused
    ]
    if use_rerank:
        scores = await rerank(query, [f"{h.section or ''}\n{h.text}" for h in hits])
        hits = [
            ClauseHit(**{**h.__dict__, "score": s})
            for h, s in sorted(zip(hits, scores, strict=True), key=lambda p: -p[1])
        ]
    return hits[:k]
