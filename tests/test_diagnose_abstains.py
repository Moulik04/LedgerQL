import json

from evals.abstain_scoring import ABSTAIN_EXPECTED_BEHAVIORS
from evals.diagnose_abstains import (
    infer_observed_behaviour,
    infer_score,
    load_jsonl,
    main,
    norm_behaviour,
)
from tests.support import require_fixture


def test_norm_behaviour_recognizes_each_canonical_value():
    assert norm_behaviour("ABSTAIN") == "ABSTAIN"
    assert norm_behaviour("refused") == "ABSTAIN"
    assert norm_behaviour("ANSWER_WITH_ASSUMPTION") == "ANSWER_WITH_ASSUMPTION"
    assert norm_behaviour("answer with a caveat") == "ANSWER_WITH_ASSUMPTION"
    assert norm_behaviour("ANSWER") == "ANSWER"
    assert norm_behaviour(None) is None


def test_infer_observed_behaviour_prefers_an_explicit_field_when_present():
    # Forward-compatibility: once a later task adds a real
    # observed_behavior field, it must win over the answer-based fallback.
    rec = {"answer": "some answer text", "observed_behavior": "ABSTAIN"}
    assert infer_observed_behaviour(rec) == "ABSTAIN"


def test_infer_observed_behaviour_falls_back_to_the_real_answer_field():
    # This is the actual bug: real per-case records have no
    # observed_behavior/observed/behavior field at all, only `answer`.
    assert infer_observed_behaviour({"answer": None}) == "ABSTAIN"
    assert infer_observed_behaviour({"answer": "a real answer"}) == "ANSWER"


def test_infer_score_prefers_an_explicit_field_when_present():
    assert infer_score({"score": 0.5, "execution_correct": True}) == 0.5


def test_infer_score_falls_back_to_execution_correct():
    assert infer_score({"execution_correct": True}) == 1.0
    assert infer_score({"execution_correct": False}) == 0.0


def test_infer_score_is_none_when_neither_field_is_present():
    # Real abstain-expected records carry neither today -- must not
    # crash or silently default to a misleading 0/1.
    assert infer_score({"answer": None, "reason_code": "OUT_OF_SCOPE"}) is None


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def test_main_reconciles_exactly_with_a_hand_computed_decision_and_strict_metrics(tmp_path, capsys):
    # A small but real scenario, computed by hand against
    # evals/abstain_scoring.py's own definition -- the same shared
    # function both this script and run_eval.py call.
    gold = [
        {"id": "A", "expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE", "tier": "t"},
        {"id": "B", "expected": "ABSTAIN", "reason_code": "SCHEMA_MISMATCH", "tier": "t"},
        {"id": "C", "expected": "ANSWER_WITH_ASSUMPTION", "reason_code": None, "tier": "t"},
        {"id": "D", "expected": "ANSWER", "reason_code": None, "tier": "t"},
    ]
    records = [
        # A: correctly abstains with the exact right reason (decision + strict).
        {"id": "A", "answer": None, "reason_code": "OUT_OF_SCOPE", "tier": "t"},
        # B: abstains on an ABSTAIN-expected case, but the wrong reason
        # code -- decision correct, strict wrong.
        {"id": "B", "answer": None, "reason_code": "LOW_AGREEMENT", "tier": "t"},
        # C: expected to abstain (ANSWER_WITH_ASSUMPTION), but answered --
        # a missed abstain, not counted in either denominator's numerator.
        {"id": "C", "answer": "here's an answer", "reason_code": None, "tier": "t"},
        # D: expected ANSWER, but abstained anyway -- a false abstain.
        {"id": "D", "answer": None, "reason_code": "LOW_AGREEMENT", "tier": "t"},
    ]

    gold_path = tmp_path / "gold.jsonl"
    report_path = tmp_path / "eval_test.jsonl"
    _write_jsonl(gold_path, gold)
    _write_jsonl(report_path, records)

    # did_abstain = {A, B, D} = 3
    # decision_correct = {A, B} (both expected in ABSTAIN_EXPECTED_BEHAVIORS) = 2
    # strict_correct = {A} (only A's reason_code matches gold's) = 1
    # expected_abstains = {A, B, C} = 3
    # precision_decision = 2/3, precision_strict = 1/3
    # recall_decision = 2/3, recall_strict = 1/3
    did_abstain = [r for r in records if r["answer"] is None]
    gold_by_id = {g["id"]: g for g in gold}
    decision_correct = [
        r for r in did_abstain if gold_by_id[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
    ]
    strict_correct = [
        r for r in decision_correct if r["reason_code"] == gold_by_id[r["id"]]["reason_code"]
    ]
    expected_abstains = [g for g in gold if g["expected"] in ABSTAIN_EXPECTED_BEHAVIORS]
    assert len(did_abstain) == 3
    assert len(decision_correct) == 2
    assert len(strict_correct) == 1
    assert len(expected_abstains) == 3

    exit_code = main([str(report_path), "--gold", str(gold_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "abstain precision (decision)" in out
    assert "abstain precision (strict)" in out
    assert "66.7%" in out  # 2/3 decision precision/recall
    assert "33.3%" in out  # 1/3 strict precision/recall


def test_main_reproduces_the_real_committed_30b_report_exactly(capsys):
    # The actual regression guard Task 0 asked for, extended for
    # PHASE_5_5_AMENDMENT_1.md's decision/strict split: run the
    # diagnostic against the real, already-scored 30B report and
    # confirm its printed metrics match the amendment's own
    # independently-verified numbers exactly. Precision, reason-code
    # accuracy and the baseline (71.0% / 29.0% / 40.9% / 33.0%) are
    # unchanged by the recall-denominator correction; recall now divides
    # by the 34 required-abstain cases rather than the 53-case union, so
    # the pair Amendment 1 cited (41.5% / 17.0%) is superseded by
    # 58.8% / 26.5%.
    from pathlib import Path

    from evals.abstain_scoring import compute_abstain_metrics

    report_path = Path("reports/eval_bridges2_qwen3_30b.jsonl")
    gold_path = Path("evals/gold.jsonl")
    require_fixture(report_path)

    records = load_jsonl(report_path)
    gold = {c["id"]: c for c in load_jsonl(gold_path)}
    metrics = compute_abstain_metrics(records, gold)

    assert metrics["all_abstains"] == 31
    assert metrics["required_abstain_cases"] == 34
    assert metrics["assumption_cases"] == 19
    assert metrics["decision_correct_abstains"] == 22
    assert metrics["strict_correct_abstains"] == 9

    exit_code = main([str(report_path), "--gold", str(gold_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "abstain precision (decision)           71.0%" in out
    assert "abstain precision (strict)             29.0%" in out
    assert "abstain recall (decision)              58.8%" in out
    assert "abstain recall (strict)                26.5%" in out
    assert "reason-code accuracy                   40.9%" in out
    # The rate alone is a denominator artifact: catching more required
    # abstains with a placeholder reason grows the denominator and can push
    # the rate down while the count of correctly-reasoned abstains rises.
    # Always print the count beside it.
    assert "(9/22 abstains that were the right call named the right reason)" in out
    assert "always-abstain baseline precision      33.0%" in out
