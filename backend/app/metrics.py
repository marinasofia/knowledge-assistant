"""Retrieval and abstention metrics. Pure functions over ranked labels, no database."""

import math
import random


def first_hits(ranked, expected):
    """1-based positions of expected items, counting each expected item once."""
    seen, positions = set(), []
    for position, item in enumerate(ranked, 1):
        if item in expected and item not in seen:
            seen.add(item)
            positions.append(position)
    return positions


def recall_at_k(ranked, expected, k=5):
    return len(first_hits(ranked[:k], expected)) / len(expected)


def reciprocal_rank(ranked, expected):
    hits = first_hits(ranked, expected)
    return 1 / hits[0] if hits else 0.0


def ndcg_at_k(ranked, expected, k=5):
    """Binary relevance nDCG (Jarvelin and Kekalainen, 2002)."""
    dcg = sum(1 / math.log2(p + 1) for p in first_hits(ranked[:k], expected))
    ideal = sum(1 / math.log2(p + 1) for p in range(1, min(len(expected), k) + 1))
    return dcg / ideal


def paired_randomization(a, b, iterations=10000, seed=7):
    """Two-sided p-value for mean(a - b) under random sign flips of the paired differences."""
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    observed = abs(sum(diffs))
    if observed == 0:
        return 1.0
    rng = random.Random(seed)
    extreme = sum(
        abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - 1e-12
        for _ in range(iterations)
    )
    return (extreme + 1) / (iterations + 1)


def risk_coverage(cases, thresholds):
    """For each threshold, how often the system answers and how often those answers were wrong.

    cases: (score, should_answer) pairs; the system answers when score >= threshold."""
    curve = []
    for t in thresholds:
        answered = [ok for score, ok in cases if score >= t]
        should = [score >= t for score, ok in cases if ok]
        curve.append(
            {
                "threshold": t,
                "coverage": round(len(answered) / len(cases), 3),
                "risk": round(answered.count(False) / len(answered), 3) if answered else 0.0,
                "wrong_abstention": round(should.count(False) / len(should), 3) if should else 0.0,
            }
        )
    return curve
