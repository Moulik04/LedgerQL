import json

from evals.diagnose_abstains import (
    ABSTAIN_EXPECTED_BEHAVIOURS,
    infer_observed_behaviour,
    infer_score,
    load_jsonl,
    main,
    norm_behaviour,
)


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


def test_main_reconciles_exactly_with_a_hand_computed_abstain_precision_and_recall(
    tmp_path, capsys
):
    # A small but real scenario, computed by hand against the same
    # definition run_eval.py's own compute_abstain_metrics() uses, to
    # guard the actual bug this task fixed: the script must derive
    # "observed behaviour" from the real `answer` field, and require an
    # exact reason_code match for "correct" -- not just a behaviour
    # match.
    gold = [
        {"id": "A", "expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE", "tier": "t"},
        {"id": "B", "expected": "ABSTAIN", "reason_code": "SCHEMA_MISMATCH", "tier": "t"},
        {"id": "C", "expected": "ANSWER_WITH_ASSUMPTION", "reason_code": None, "tier": "t"},
        {"id": "D", "expected": "ANSWER", "reason_code": None, "tier": "t"},
    ]
    records = [
        # A: correctly abstains with the exact right reason.
        {"id": "A", "answer": None, "reason_code": "OUT_OF_SCOPE", "tier": "t"},
        # B: abstains, but the wrong reason code -- not "correct".
        {"id": "B", "answer": None, "reason_code": "LOW_AGREEMENT", "tier": "t"},
        # C: expected to abstain (ANSWER_WITH_ASSUMPTION), but answered --
        # a missed abstain, not counted in the abstain precision denominator.
        {"id": "C", "answer": "here's an answer", "reason_code": None, "tier": "t"},
        # D: expected ANSWER, but abstained anyway -- a false abstain.
        {"id": "D", "answer": None, "reason_code": "LOW_AGREEMENT", "tier": "t"},
    ]

    gold_path = tmp_path / "gold.jsonl"
    report_path = tmp_path / "eval_test.jsonl"
    _write_jsonl(gold_path, gold)
    _write_jsonl(report_path, records)

    # Hand-computed against run_eval.py's own definition:
    # did_abstain = {A, B, D} = 3
    # correct_abstain = {A} (only A has expected in ABSTAIN_EXPECTED_BEHAVIOURS
    #   and an exact reason_code match) = 1
    # expected_abstain_recs = {A, B, C} = 3
    # precision = 1/3, recall = 1/3
    did_abstain = [r for r in records if r["answer"] is None]
    correct = [
        r
        for r in did_abstain
        if {g["id"]: g for g in gold}[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIOURS
        and r["reason_code"] == {g["id"]: g for g in gold}[r["id"]]["reason_code"]
    ]
    expected_abstains = [g for g in gold if g["expected"] in ABSTAIN_EXPECTED_BEHAVIOURS]
    assert len(did_abstain) == 3
    assert len(correct) == 1
    assert len(expected_abstains) == 3

    exit_code = main([str(report_path), "--gold", str(gold_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "abstain precision" in out
    assert "33.3%" in out  # 1/3 precision
    # Recall also 1/3 -- both percentages appear together, distinguished
    # by their labeled lines rather than searched for independently here.
    assert "abstain recall" in out


def test_main_reproduces_the_real_committed_30b_report_exactly(capsys):
    # The actual regression guard Task 0 asked for: run the diagnostic
    # against the real, already-scored 30B report and confirm its
    # printed abstain precision/recall match the report's own numbers
    # exactly (29.0% / 17.0%), and that the invariants hold:
    # correct + false == total_abstains, correct + missed == expected_abstains
    # (using the strict two-way complement of each, not the finer
    # correct/false/wrong-reason-code three-way breakdown the human-
    # readable report sections print).
    from pathlib import Path

    report_path = Path("reports/eval_bridges2_qwen3_30b.jsonl")
    gold_path = Path("evals/gold.jsonl")
    if not report_path.exists():
        import pytest

        pytest.skip("local-only Bridges-2 report not present in this checkout")

    records = load_jsonl(report_path)
    gold = {c["id"]: c for c in load_jsonl(gold_path)}

    did_abstain = [r for r in records if r["answer"] is None]
    correct = [
        r
        for r in did_abstain
        if gold[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIOURS
        and r.get("reason_code") == gold[r["id"]].get("reason_code")
    ]
    expected_abstains = [c for c in gold.values() if c["expected"] in ABSTAIN_EXPECTED_BEHAVIOURS]

    total_abstains = len(did_abstain)
    n_correct = len(correct)
    n_expected = len(expected_abstains)
    false_total = total_abstains - n_correct
    missed_total = n_expected - n_correct

    assert n_correct + false_total == total_abstains
    assert n_correct + missed_total == n_expected
    assert n_correct == 9
    assert total_abstains == 31
    assert n_expected == 53

    exit_code = main([str(report_path), "--gold", str(gold_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "abstain precision                  29.0%" in out
    assert "abstain recall                     17.0%" in out
    assert "always-abstain baseline precision  33.0%" in out
