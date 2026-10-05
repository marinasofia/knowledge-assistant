import math

from app.metrics import (
    ndcg_at_k,
    paired_randomization,
    recall_at_k,
    reciprocal_rank,
    risk_coverage,
)


def test_rank_metrics_on_hand_computed_example():
    ranked = ["x", "a", "y", "b", "a"]
    expected = {"a", "b"}
    assert recall_at_k(ranked, expected) == 1.0
    assert recall_at_k(ranked, expected, k=2) == 0.5
    assert reciprocal_rank(ranked, expected) == 0.5
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    assert math.isclose(ndcg_at_k(ranked, expected), dcg / (1 + 1 / math.log2(3)))
    assert reciprocal_rank(["x"], expected) == 0.0 and ndcg_at_k(["x"], expected) == 0.0


def test_duplicate_hits_count_once():
    assert ndcg_at_k(["a", "a"], {"a", "b"}) == 1 / (1 + 1 / math.log2(3))


def test_randomization_test_separates_noise_from_signal():
    assert paired_randomization([0.5] * 10, [0.5] * 10) == 1.0
    assert paired_randomization([1.0] * 20, [0.0] * 20) < 0.001
    assert paired_randomization([1, 0, 1, 0], [0, 1, 0, 1]) > 0.5


def test_risk_coverage_curve():
    cases = [(0.9, True), (0.5, True), (0.3, False), (0.2, True), (0.1, False)]
    low, mid = risk_coverage(cases, [0.0, 0.4])
    assert low == {"threshold": 0.0, "coverage": 1.0, "risk": 0.4, "wrong_abstention": 0.0}
    assert mid == {"threshold": 0.4, "coverage": 0.4, "risk": 0.0, "wrong_abstention": 0.333}
