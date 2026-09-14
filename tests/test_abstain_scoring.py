from evals.abstain_scoring import (
    ABSTAIN_EXPECTED_BEHAVIORS,
    acceptable_reason_codes,
    compute_abstain_metrics,
)


def test_acceptable_reason_codes_includes_gold_reason_code():
    gold = {"reason_code": "OUT_OF_SCOPE"}
    assert acceptable_reason_codes(gold) == {"OUT_OF_SCOPE"}


def test_acceptable_reason_codes_parses_abstain_alternatives():
    # Real gold.jsonl pattern (Phase 5.5 Amendment 1, part B): O04 expects
    # SCHEMA_MISMATCH but accepts OUT_OF_SCOPE as an alternative.
    gold = {"reason_code": "SCHEMA_MISMATCH", "accept_alternatives": ["ABSTAIN:OUT_OF_SCOPE"]}
    assert acceptable_reason_codes(gold) == {"SCHEMA_MISMATCH", "OUT_OF_SCOPE"}


def test_acceptable_reason_codes_ignores_non_abstain_alternatives():
    # Real pattern: M02's second alternative is an ANSWER_WITH_ASSUMPTION
    # variant, not an "ABSTAIN:CODE" -- not a reason code at all.
    gold = {
        "reason_code": None,
        "accept_alternatives": [
            "ABSTAIN:AMBIGUOUS",
            "ANSWER_WITH_ASSUMPTION using total_assets instead, if stated",
        ],
    }
    assert acceptable_reason_codes(gold) == {"AMBIGUOUS"}


def test_acceptable_reason_codes_handles_trailing_explanation_text():
    # Real pattern: M04's alternative has explanatory prose after the code.
    gold = {
        "reason_code": "AMBIGUOUS",
        "accept_alternatives": [
            "ABSTAIN:SCHEMA_MISMATCH — since no quarterly data exists at all, "
            "this is arguably the primary reason"
        ],
    }
    assert acceptable_reason_codes(gold) == {"AMBIGUOUS", "SCHEMA_MISMATCH"}


def test_acceptable_reason_codes_empty_when_none_and_no_alternatives():
    assert acceptable_reason_codes({"reason_code": None}) == set()
    assert acceptable_reason_codes({}) == set()


def _case(case_id, expected, reason_code=None, accept_alternatives=None):
    c = {"id": case_id, "expected": expected, "reason_code": reason_code}
    if accept_alternatives is not None:
        c["accept_alternatives"] = accept_alternatives
    return c


def _record(case_id, answer, reason_code=None):
    return {"id": case_id, "answer": answer, "reason_code": reason_code}


def test_compute_abstain_metrics_distinguishes_decision_from_strict():
    # A abstains for the exact right reason (both decision and strict
    # correct); B abstains on an ABSTAIN-expected case but names a
    # different, unacceptable reason (decision correct, strict wrong).
    cases_by_id = {
        "A": _case("A", "ABSTAIN", "OUT_OF_SCOPE"),
        "B": _case("B", "ABSTAIN", "SCHEMA_MISMATCH"),
    }
    per_case = [
        _record("A", None, "OUT_OF_SCOPE"),
        _record("B", None, "LOW_AGREEMENT"),
    ]

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 2
    assert metrics["expected_abstains"] == 2
    assert metrics["decision_correct_abstains"] == 2
    assert metrics["strict_correct_abstains"] == 1
    assert metrics["abstain_precision_decision"] == 1.0
    assert metrics["abstain_precision_strict"] == 0.5
    assert metrics["abstain_recall_decision"] == 1.0
    assert metrics["abstain_recall_strict"] == 0.5
    assert metrics["reason_code_accuracy"] == 0.5


def test_compute_abstain_metrics_honors_accept_alternatives_for_strict():
    cases_by_id = {
        "A": _case("A", "ABSTAIN", "SCHEMA_MISMATCH", accept_alternatives=["ABSTAIN:OUT_OF_SCOPE"]),
    }
    per_case = [_record("A", None, "OUT_OF_SCOPE")]

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["strict_correct_abstains"] == 1
    assert metrics["abstain_precision_strict"] == 1.0
    assert metrics["reason_code_accuracy"] == 1.0


def test_compute_abstain_metrics_answered_case_not_counted_as_abstain():
    cases_by_id = {"A": _case("A", "ABSTAIN", "OUT_OF_SCOPE")}
    per_case = [_record("A", "an answer", None)]

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 0
    assert metrics["abstain_precision_decision"] == 0.0
    assert metrics["abstain_precision_strict"] == 0.0
    assert metrics["abstain_recall_decision"] == 0.0
    assert metrics["reason_code_accuracy"] == 0.0


def test_compute_abstain_metrics_counts_answer_with_assumption_as_expected():
    cases_by_id = {"A": _case("A", "ANSWER_WITH_ASSUMPTION", None)}
    per_case = [_record("A", None, "LOW_AGREEMENT")]

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["expected_abstains"] == 1
    assert metrics["decision_correct_abstains"] == 1  # right to abstain...
    assert metrics["strict_correct_abstains"] == 0  # ...but no acceptable reason matched


def test_compute_abstain_metrics_false_abstain_not_counted_anywhere_as_correct():
    cases_by_id = {"A": _case("A", "ANSWER")}
    per_case = [_record("A", None, "LOW_AGREEMENT")]

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 1
    assert metrics["decision_correct_abstains"] == 0
    assert metrics["expected_abstains"] == 0


def test_compute_abstain_metrics_reproduces_the_real_30b_report_numbers():
    # Phase 5.5 Amendment 1's own cited numbers, independently verified
    # against the real committed report: 71.0% / 29.0% / 41.5% / 17.0% / 40.9%.
    import json
    from pathlib import Path

    report_path = Path("reports/eval_bridges2_qwen3_30b.jsonl")
    gold_path = Path("evals/gold.jsonl")
    if not report_path.exists():
        import pytest

        pytest.skip("local-only Bridges-2 report not present in this checkout")

    per_case = [json.loads(line) for line in report_path.read_text().splitlines() if line.strip()]
    cases_by_id = {
        c["id"]: c
        for c in (json.loads(line) for line in gold_path.read_text().splitlines() if line.strip())
    }

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 31
    assert metrics["expected_abstains"] == 53
    assert metrics["decision_correct_abstains"] == 22
    assert metrics["strict_correct_abstains"] == 9
    assert round(metrics["abstain_precision_decision"], 3) == 0.710
    assert round(metrics["abstain_precision_strict"], 3) == 0.290
    assert round(metrics["abstain_recall_decision"], 3) == 0.415
    assert round(metrics["abstain_recall_strict"], 3) == 0.170
    assert round(metrics["reason_code_accuracy"], 3) == 0.409


def test_abstain_expected_behaviors_is_the_canonical_set():
    assert ABSTAIN_EXPECTED_BEHAVIORS == {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}
