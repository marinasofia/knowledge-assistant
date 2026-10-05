"""Reproducible retrieval and outcome evaluation, not human grounding certification."""

import argparse
import json
from pathlib import Path
from statistics import mean

from .answers import MIN_COVERAGE, generate, retrieve
from .config import settings
from .db import transaction
from .metrics import ndcg_at_k, paired_randomization, recall_at_k, reciprocal_rank, risk_coverage
from .policy import find_conflicts

THRESHOLDS = [round(t * 0.05, 2) for t in range(21)]


def outcome_summary(details):
    summary = {}
    for d in details:
        row = summary.setdefault(d["category"], {"matched": 0, "cases": 0})
        row["matched"] += d["outcome"] == d["expected_outcome"]
        row["cases"] += 1
    return summary


def run_mode(cases):
    details = []
    for case in cases:
        with transaction("northstar") as conn:
            sources = retrieve(conn, case["question"])
            conflicts = find_conflicts(conn, sources)
        ranked = [(s["title"], s["section"]) for s in sources]
        expected = {tuple(s) for s in case["expected_sources"]}
        row = {
            "id": case["id"],
            "category": case["category"],
            "expected_outcome": case["expected_outcome"],
            "outcome": generate(case["question"], sources, conflicts).status,
            "top_coverage": round(max((s["coverage"] for s in sources), default=0.0), 3),
            "retrieved": len(sources),
        }
        if expected:
            row.update(
                recall=recall_at_k(ranked, expected),
                reciprocal_rank=reciprocal_rank(ranked, expected),
                ndcg=round(ndcg_at_k(ranked, expected), 4),
            )
        details.append(row)
    labeled = [d for d in details if "recall" in d]
    curve_cases = [(d["top_coverage"], d["expected_outcome"] != "abstain") for d in details]
    return {
        "case_count": len(details),
        "labeled_cases": len(labeled),
        "recall_at_5": round(mean(d["recall"] for d in labeled), 4),
        "mrr": round(mean(d["reciprocal_rank"] for d in labeled), 4),
        "ndcg_at_5": round(mean(d["ndcg"] for d in labeled), 4),
        "outcomes": outcome_summary(details),
        "abstention_curve": risk_coverage(curve_cases, THRESHOLDS),
        "details": details,
    }


def evaluate(split):
    if settings.generation_mode != "evidence":
        raise SystemExit("Evaluation measures local evidence mode only; no provider calls.")
    root = Path(__file__).resolve().parents[2]
    cases = [c for c in json.loads((root / "evaluations/cases.json").read_text())]
    cases = [c for c in cases if c["split"] == split]
    report = {
        "split": split,
        "label_status": "draft_requires_human_review",
        "corpus_documents": 6,
        "human_claim_support": "not_measured",
        "live_generation": "not_measured",
        "outcome_rule": f"local evidence mode, top passage coverage >= {MIN_COVERAGE}",
        "modes": {},
    }
    for mode in ["keyword", "hybrid"]:
        settings.semantic_search = mode == "hybrid"
        report["modes"][mode] = run_mode(cases)
    keyword, hybrid = (
        [d["ndcg"] for d in report["modes"][m]["details"] if "ndcg" in d]
        for m in ("keyword", "hybrid")
    )
    report["keyword_vs_hybrid"] = {
        "metric": "ndcg_at_5",
        "mean_difference": round(mean(keyword) - mean(hybrid), 4),
        "p_value": round(paired_randomization(keyword, hybrid), 4),
        "test": "paired randomization, 10000 sign flips, seed 7",
    }
    output = root / "evaluations" / f"{split}-report.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    summary = {
        mode: {k: v for k, v in value.items() if k not in {"details", "abstention_curve"}}
        for mode, value in report["modes"].items()
    }
    print(json.dumps({"split": split, **summary, "comparison": report["keyword_vs_hybrid"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["development", "held-out"], required=True)
    evaluate(parser.parse_args().split)
