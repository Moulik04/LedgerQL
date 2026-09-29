from pathlib import Path

import pytest

from evals.signal_precheck import (
    auroc,
    bootstrap_auroc_ci,
    build_rows,
    cross_model_pairs,
    load_jsonl,
    rows_equivalent,
    signal_report,
)
from tests.support import require_fixture

REPORTS = Path("reports")
DB = Path("data/ledgerql.duckdb")
GOLD = Path("evals/gold.jsonl")


def test_auroc_is_one_for_perfect_separation_and_half_for_a_constant_score():
    assert auroc([1.0, 1.0], [0.0, 0.0]) == 1.0
    assert auroc([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert auroc([1, 1, 1], [1, 1]) == 0.5  # every pair tied
    assert auroc([], [1]) is None  # undefined, not 0.0


def test_auroc_counts_ties_as_half():
    assert auroc([1.0, 0.0], [0.0]) == 0.75  # (1 win + 1 tie) / 2 pairs


def test_bootstrap_ci_brackets_the_point_estimate_and_is_reproducible():
    pos, neg = [1, 1, 1, 0.5, 0.5, 0], [1, 0.5, 0, 0, 0]
    lo, hi = bootstrap_auroc_ci(pos, neg, n_boot=500, seed=0)
    assert lo <= auroc(pos, neg) <= hi
    assert (lo, hi) == bootstrap_auroc_ci(pos, neg, n_boot=500, seed=0)


def test_rows_equivalent_ignores_row_order_and_float_noise():
    assert rows_equivalent([(1, 2.0), (3, 4.0)], [(3, 4.0 + 1e-9), (1, 2.0)])
    assert not rows_equivalent([(1, 2.0)], [(1, 2.5)])
    assert not rows_equivalent([(1,)], [(1,), (2,)])  # different row counts
    assert rows_equivalent([], [])


def test_cross_model_pairs_only_covers_cases_both_models_answered():
    a = [
        {"id": "X1", "answered": True, "winner_correct": True, "winner_rows": [(1,)]},
        {"id": "X2", "answered": True, "winner_correct": False, "winner_rows": [(2,)]},
        {"id": "X3", "answered": False, "winner_correct": False, "winner_rows": None},
    ]
    b = [
        {"id": "X1", "answered": True, "winner_correct": True, "winner_rows": [(1,)]},
        {"id": "X2", "answered": True, "winner_correct": False, "winner_rows": [(3,)]},
        {"id": "X3", "answered": True, "winner_correct": True, "winner_rows": [(9,)]},
    ]
    pairs = cross_model_pairs(a, b)
    assert [p["id"] for p in pairs] == ["X1", "X2"]  # X3: model A abstained
    assert [p["xmodel_match"] for p in pairs] == [1, 0]
    assert pairs[0]["correct_a"] is True and pairs[1]["correct_b"] is False


def test_signal_report_flags_constant_signals_as_chance_by_construction():
    rows = [
        {"answered": True, "winner_correct": True, "agreement": 1.0, "guardrail_clean": 1},
        {"answered": True, "winner_correct": False, "agreement": 0.6, "guardrail_clean": 1},
    ]
    report = signal_report(rows, ["agreement", "guardrail_clean"])
    assert report["agreement"]["auroc"] == 1.0
    assert report["guardrail_clean"]["auroc"] == 0.5
    assert report["guardrail_clean"]["constant"] is True
    assert report["agreement"]["constant"] is False


@pytest.fixture(scope="module")
def real_rows():
    gold = {c["id"]: c for c in load_jsonl(require_fixture(GOLD))}
    out = {}
    for model in ("qwen3_30b", "qwen25_32b"):
        report = require_fixture(REPORTS / f"eval_bridges2_{model}_measured.jsonl")
        out[model] = build_rows(load_jsonl(report), gold, str(require_fixture(DB)))
    return out


def test_shipped_config_answered_and_wrong_counts_match_the_published_rates(real_rows):
    # DECISIONS.md 2026-09-23: confidently-wrong 41.8% (30B) and 40.9% (32B).
    for model, answered, wrong in (("qwen3_30b", 55, 23), ("qwen25_32b", 44, 18)):
        ans = [r for r in real_rows[model] if r["answered"]]
        assert len(ans) == answered
        assert sum(not r["winner_correct"] for r in ans) == wrong


def test_recomputed_agreement_equals_the_logged_confidence(real_rows):
    # Confirms the offline vote reproduces the live one, so every signal built
    # on the re-executed candidates is the signal the pipeline actually had.
    for rows in real_rows.values():
        for r in rows:
            if r["logged_confidence"] is not None:
                assert r["agreement"] == pytest.approx(r["logged_confidence"]), r["id"]
