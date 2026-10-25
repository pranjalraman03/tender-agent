from evals.metrics import criterion_scores, p50_p95, recall_at_k, regressions
from evals.schema import GoldCriterion

GOLD = [
    GoldCriterion(description="turnover", status="met", evidence=["at least Rs. 50 lakh"]),
    GoldCriterion(description="iso", status="not_met", evidence=["ISO  9001"]),
]


def test_recall_at_k() -> None:
    retrieved = [["noise", "Turnover shall be AT LEAST rs. 50 lakh"], ["noise", "noise"]]
    assert recall_at_k(retrieved, GOLD, k=1) == 0.0
    assert recall_at_k(retrieved, GOLD, k=2) == 0.5


def test_criterion_scores() -> None:
    predicted = [
        {"status": "met", "clause_texts": ["turnover at least Rs. 50 lakh"]},  # TP
        {"status": "met", "clause_texts": ["valid ISO 9001 certificate"]},  # wrong status
        {"status": "met", "clause_texts": ["unrelated clause"]},  # no match
    ]
    p, r, f1 = criterion_scores(predicted, GOLD)
    assert (round(p, 3), r) == (0.333, 0.5)
    assert round(f1, 3) == 0.4


def test_regressions() -> None:
    base = {"verdict_accuracy": 0.8, "cost_usd_p50": 0.10}
    assert regressions({"verdict_accuracy": 0.77, "cost_usd_p50": 0.12}, base) == []
    bad = regressions({"verdict_accuracy": 0.70, "cost_usd_p50": 0.20}, base)
    assert len(bad) == 2


def test_p50_p95() -> None:
    assert p50_p95([]) == (0.0, 0.0)
    p50, p95 = p50_p95([1.0, 2.0, 3.0, 4.0, 100.0])
    assert p50 == 3.0 and p95 > 4.0
