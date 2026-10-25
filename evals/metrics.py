"""Metric functions (pure, unit-tested)."""

from statistics import quantiles
from typing import Any

from evals.schema import GoldCriterion, clause_hits


def recall_at_k(retrieved: list[list[str]], gold: list[GoldCriterion], k: int) -> float:
    """retrieved[i] = clause texts returned for gold[i]'s query, best first."""
    if not gold:
        return 1.0
    hits = sum(any(clause_hits(t, g) for t in r[:k]) for r, g in zip(retrieved, gold, strict=True))
    return hits / len(gold)


def criterion_scores(
    predicted: list[dict[str, Any]], gold: list[GoldCriterion]
) -> tuple[float, float, float]:
    """Precision / recall / F1 over (criterion, status) pairs.

    predicted: [{"status": ..., "clause_texts": [...]}]. A prediction matches a gold
    criterion when one of its cited clauses contains the gold evidence; it is a true
    positive when the statuses also agree. Each gold criterion matches at most once.
    """
    used: set[int] = set()
    tp = 0
    for p in predicted:
        for i, g in enumerate(gold):
            if i in used:
                continue
            if any(clause_hits(t, g) for t in p["clause_texts"]):
                used.add(i)
                tp += p["status"] == g.status
                break
    precision = tp / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = tp / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def p50_p95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], values[0]
    qs = quantiles(values, n=100, method="inclusive")
    return qs[49], qs[94]


# metric -> (direction, tolerance). direction +1: higher is better; -1: lower is better.
# Tolerances are absolute for rates and relative (fraction) for cost/latency.
TOLERANCES: dict[str, tuple[int, float, str]] = {
    "retrieval_recall_at_5": (1, 0.03, "abs"),
    "retrieval_recall_at_10": (1, 0.03, "abs"),
    "verdict_accuracy": (1, 0.05, "abs"),
    "criterion_f1": (1, 0.05, "abs"),
    "citation_precision": (1, 0.05, "abs"),
    "cost_usd_p50": (-1, 0.25, "rel"),
    "latency_s_p95": (-1, 0.25, "rel"),
}


def regressions(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    out = []
    for name, (direction, tol, kind) in TOLERANCES.items():
        if name not in current or name not in baseline:
            continue
        cur, base = current[name], baseline[name]
        allowed = tol if kind == "abs" else abs(base) * tol
        if direction * (cur - base) < -allowed:
            out.append(
                f"{name}: {base:.4f} -> {cur:.4f} (tolerance {tol}{'' if kind == 'abs' else 'x'})"
            )
    return out
