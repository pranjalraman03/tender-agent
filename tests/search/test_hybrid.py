import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.llm.embeddings import embed, to_pgvector
from core.search.hybrid import rrf, search_clauses


def test_rrf_rewards_agreement() -> None:
    fused = rrf([1, 2, 3], [3, 1, 4])
    ids = [cid for cid, _ in fused]
    assert ids[0] == 1  # rank 1 + rank 2
    assert ids[1] == 3  # rank 3 + rank 1
    assert set(ids) == {1, 2, 3, 4}
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_rrf_empty() -> None:
    assert rrf([], []) == []


CLAUSES = [
    ("1", "General", "The bid must be submitted online through the CPPP portal."),
    (
        "4.1",
        "Eligibility",
        "Average annual financial turnover of the bidder during the last "
        "three financial years shall be at least Rs 50 lakh.",
    ),
    (
        "4.2",
        "Eligibility",
        "The bidder should have completed three similar works of value "
        "not less than Rs 20 lakh each in the last seven years.",
    ),
    ("6", "EMD", "Micro and small enterprises registered with Udyam are exempt from EMD."),
]


@pytest.mark.slow
async def test_search_finds_turnover_clause(
    sessionmaker: async_sessionmaker[AsyncSession], portal_id: int
) -> None:
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
        doc_id = (
            await s.execute(
                text(
                    "INSERT INTO tender_documents (tender_id, storage_key, sha256) "
                    "VALUES (:t, 'k', 'sha') RETURNING id"
                ),
                {"t": tender_id},
            )
        ).scalar_one()
        vectors = await embed([f"{sec}\n{t}" for _, sec, t in CLAUSES])
        for (no, sec, body), v in zip(CLAUSES, vectors, strict=True):
            await s.execute(
                text(
                    "INSERT INTO clauses (document_id, tender_id, clause_no, section, page_start, "
                    "page_end, text, embedding) VALUES (:d, :t, :no, :sec, 1, 1, :body, "
                    "CAST(:v AS vector))"
                ),
                {
                    "d": doc_id,
                    "t": tender_id,
                    "no": no,
                    "sec": sec,
                    "body": body,
                    "v": to_pgvector(v),
                },
            )

    async with sessionmaker() as s:
        hits = await search_clauses(s, tender_id, "minimum turnover requirement", k=2)
        emd = await search_clauses(s, tender_id, "EMD exemption for MSE", k=1)
        only_elig = await search_clauses(s, tender_id, "turnover", section="eligib")
    assert hits[0].clause_no == "4.1"
    assert emd[0].clause_no == "6"
    assert {h.section for h in only_elig} == {"Eligibility"}
