import pytest

from evals.run_eval import results_match


def test_results_match_scalar_within_tolerance():
    assert results_match([(391035000000.0,)], [(391035000000.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(391035000001.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(1.0,)], "scalar") is False


def test_results_match_scalar_respects_custom_tolerance():
    assert results_match([(100.0,)], [(105.0,)], "scalar", tolerance=0.05) is True
    assert results_match([(100.0,)], [(106.0,)], "scalar", tolerance=0.05) is False


def test_results_match_empty():
    assert results_match([], [], "empty") is True
    assert results_match([], [(1,)], "empty") is False


def test_results_match_set_ignores_order():
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], "set") is True
    assert results_match([(1, "a")], [(2, "b")], "set") is False


def test_results_match_ordered_requires_same_order():
    assert results_match([(1,), (2,)], [(1,), (2,)], "ordered") is True
    assert results_match([(1,), (2,)], [(2,), (1,)], "ordered") is False


def test_results_match_scalar_or_null_treats_both_none_as_match():
    assert results_match([(None,)], [(None,)], "scalar_or_null") is True
    assert results_match([(None,)], [(5.0,)], "scalar_or_null") is False


def test_results_match_raises_on_unknown_compare_value():
    with pytest.raises(ValueError, match="unknown compare value"):
        results_match([(1,)], [(1,)], "not_a_real_compare_type")


def test_results_match_none_always_true():
    # "none" is structurally unreachable today (an ANSWER-expected gold
    # case always carries a real compare type), but must not raise.
    assert results_match([], [], "none") is True
    assert results_match([(1,)], [(2, 3)], "none") is True


def test_write_reports_serializes_date_values_in_rows(tmp_path):
    # DuckDB returns datetime.date for DATE columns (e.g. period_end_date);
    # a per-case record's "rows" can carry these straight from the DB, and
    # write_reports must not crash writing the jsonl report.
    import json
    from datetime import date as date_type

    from evals.run_eval import write_reports

    summary = {
        "overall_execution_accuracy": 1.0,
        "all_tiers": ["lookup"],
        "per_tier_accuracy": {"lookup": 1.0},
        "guardrail_catch_rate": {},
        "hallucinated_number_rate": 0.0,
        "answered_count": 1,
        "non_answer_case_count": 0,
        "non_answer_attempted": 0,
        "non_answer_errored": 0,
        "non_answer_tier_breakdown": {},
        "all_abstains": 0,
        "correct_abstains": 0,
        "expected_abstains": 0,
        "abstain_precision": 0.0,
        "abstain_recall": 0.0,
        "per_case": [
            {
                "id": "L01",
                "tier": "lookup",
                "rows": [(date_type(2024, 9, 28), 391035000000.0)],
            }
        ],
    }

    md_path, jsonl_path = write_reports(summary, tmp_path)
    record = json.loads(jsonl_path.read_text().splitlines()[0])
    assert record["rows"][0][0] == "2024-09-28"
    assert md_path.exists()
    assert md_path.name == "eval.md"
    assert jsonl_path.name.startswith("eval_")


def test_score_guardrail_case_passes_when_blocked_with_correct_reason():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": "read_only"}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": ["read_only"]}
    score = score_guardrail_case(case, result)
    assert score == {"blocked": True, "reason_correct": True, "guardrail_ok": True, "passed": True}


def test_score_guardrail_case_fails_when_not_blocked():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    result = {"answer": "some answer", "reason_code": None, "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["blocked"] is False
    assert score["passed"] is False


def test_score_guardrail_case_fails_on_wrong_reason_code():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "SCHEMA_MISMATCH", "guardrail_must_fire": None}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["reason_correct"] is False
    assert score["passed"] is False


def test_score_guardrail_case_ignores_guardrail_tag_when_not_required():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is True
    assert score["passed"] is True


def test_score_guardrail_case_fails_when_required_tag_missing():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "COST_LIMIT", "guardrail_must_fire": "cost_limit"}
    result = {"answer": None, "reason_code": "COST_LIMIT", "guardrail_events": ["single_statement"]}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is False
    assert score["passed"] is False


def test_run_skips_guardrail_scoring_for_answer_expected_in_guardrail_tiers(tmp_path, monkeypatch):
    # A case with tier in GUARDRAIL_SCORED_TIERS but expected == "ANSWER"
    # (e.g., adversarial S09/S10) must NOT be counted in guardrail_total,
    # even if the pipeline blocks it or answers correctly. It is scored only
    # through the execution-accuracy path (if expected == "ANSWER").
    import json

    from evals.run_eval import run

    # Create a minimal gold.jsonl with:
    # - One adversarial case with expected == "ANSWER" (should NOT be in guardrail_total)
    # - One out_of_scope case with expected == "ABSTAIN" (should be in guardrail_total)
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "id": "ADV_ANSWER",
                "tier": "adversarial",
                "expected": "ANSWER",
                "question": "What is 2+2?",
                "gold_sql": "SELECT 4",
                "compare": "scalar",
                "reason_code": None,
                "guardrail_must_fire": None,
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "OUT_ABSTAIN",
                "tier": "out_of_scope",
                "expected": "ABSTAIN",
                "question": "Malicious prompt here",
                "gold_sql": "SELECT 1",
                "compare": "scalar",
                "reason_code": "OUT_OF_SCOPE",
                "guardrail_must_fire": None,
            }
        )
    )

    # Mock pipeline.ask to return correct answer for first case, blocked for second
    def mock_ask(question, db_path=None):
        if "2+2" in question:
            return {
                "sql": "SELECT 4",
                "error": None,
                "answer": "4",
                "columns": ["result"],
                "rows": [(4,)],
                "truncated": False,
                "reason_code": None,
                "guardrail_events": [],
            }
        else:  # malicious prompt
            return {
                "sql": None,
                "error": None,
                "answer": None,
                "columns": [],
                "rows": [],
                "truncated": False,
                "reason_code": "OUT_OF_SCOPE",
                "guardrail_events": [],
            }

    # Mock duckdb.connect to return a mock connection
    class MockConnection:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [(4,)]

        def close(self):
            pass

    monkeypatch.setattr("ledgerql.pipeline.ask", mock_ask)
    monkeypatch.setattr("duckdb.connect", lambda *args, **kwargs: MockConnection())

    summary = run(gold_path, "dummy.db")

    # The adversarial ANSWER case should NOT be in guardrail_total
    assert "adversarial" not in summary["guardrail_catch_rate"]
    # The out_of_scope ABSTAIN case should be in guardrail_total
    assert "out_of_scope" in summary["guardrail_catch_rate"]
    assert summary["guardrail_catch_rate"]["out_of_scope"] == 1.0


def test_compute_abstain_metrics_counts_correct_abstain():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "A1", "answer": None, "reason_code": "OUT_OF_SCOPE"}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 1
    assert metrics["correct_abstains"] == 1
    assert metrics["expected_abstains"] == 1
    assert metrics["abstain_precision"] == 1.0
    assert metrics["abstain_recall"] == 1.0


def test_compute_abstain_metrics_wrong_reason_code_not_correct():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "A1", "answer": None, "reason_code": "SCHEMA_MISMATCH"}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["correct_abstains"] == 0
    assert metrics["abstain_precision"] == 0.0


def test_compute_abstain_metrics_answered_case_not_counted_as_abstain():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "L1", "answer": "the value is 5", "reason_code": None}]
    cases_by_id = {"L1": {"expected": "ANSWER", "reason_code": None}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 0
    assert metrics["expected_abstains"] == 0
    assert metrics["abstain_precision"] == 0.0
    assert metrics["abstain_recall"] == 0.0


def test_compute_abstain_metrics_missed_expected_abstain_hurts_recall():
    from evals.run_eval import compute_abstain_metrics

    # Expected to abstain, but the pipeline answered anyway.
    per_case = [{"id": "A1", "answer": "a wrong answer", "reason_code": None}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["expected_abstains"] == 1
    assert metrics["correct_abstains"] == 0
    assert metrics["abstain_recall"] == 0.0


def test_compute_abstain_metrics_counts_answer_with_assumption_as_expected():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "L3", "answer": None, "reason_code": "AMBIGUOUS"}]
    cases_by_id = {"L3": {"expected": "ANSWER_WITH_ASSUMPTION", "reason_code": "AMBIGUOUS"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["expected_abstains"] == 1
    assert metrics["correct_abstains"] == 1
