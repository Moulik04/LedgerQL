from pathlib import Path

from evals.comparator_audit import (
    apply_relaxed,
    audit,
    context_columns,
    load_jsonl,
    relaxed_match,
)
from tests.support import require_fixture


def test_a_context_column_is_one_named_as_context_and_constant_across_gold_rows():
    cols = ["value", "period_end_date", "fiscal_year"]
    single_row = [(1.0, "2024-09-28", 2024)]
    assert context_columns(cols, single_row) == {1, 2}
    series = [(1.0, "2023-09-30", 2023), (2.0, "2024-09-28", 2024)]
    # Varying context labels the values: it is part of the answer, not context.
    assert context_columns(cols, series) == set()


def test_a_gold_result_that_is_all_context_keeps_its_columns():
    assert context_columns(["fiscal_year"], [(2024,)]) == set()


def test_u02s_shape_matches_once_context_columns_are_optional():
    # Gold returns (value, period_end_date); the model returned the right value only.
    gold_cols, gold_rows = ["value", "period_end_date"], [(391035000000.0, "2024-09-28")]
    assert relaxed_match({"compare": "set"}, gold_cols, gold_rows, ["value"], [(391035000000.0,)])


def test_extra_context_columns_from_the_model_are_ignored_by_name():
    gold_cols, gold_rows = ["value"], [(5.0,)]
    pred_cols, pred_rows = ["fiscal_year", "value"], [(2024, 5.0)]
    assert relaxed_match({"compare": "set"}, gold_cols, gold_rows, pred_cols, pred_rows)


def test_a_required_series_year_column_is_kept_on_the_prediction_too():
    gold_cols, gold_rows = ["fiscal_year", "value"], [(2023, 1.0), (2024, 2.0)]
    swapped = [(2023, 2.0), (2024, 1.0)]
    assert relaxed_match({"compare": "set"}, gold_cols, gold_rows, gold_cols, gold_rows)
    assert not relaxed_match({"compare": "set"}, gold_cols, gold_rows, gold_cols, swapped)


def test_a_wrong_target_value_still_fails():
    gold_cols, gold_rows = ["value", "period_end_date"], [(5.0, "2024-09-28")]
    assert not relaxed_match({"compare": "set"}, gold_cols, gold_rows, ["value"], [(6.0,)])


def test_a_series_answer_without_its_year_column_still_fails():
    gold_cols = ["fiscal_year", "value"]
    gold_rows = [(2023, 1.0), (2024, 2.0)]
    # Same numbers, no year labels: which value belongs to which year is unknowable.
    assert not relaxed_match({"compare": "set"}, gold_cols, gold_rows, ["value"], [(1.0,), (2.0,)])


def test_scalar_compare_keeps_its_one_cell_shape_after_projection():
    gold_cols, gold_rows = ["value", "uom"], [(5.0, "USD")]
    assert relaxed_match({"compare": "scalar"}, gold_cols, gold_rows, ["value"], [(5.0,)])
    assert not relaxed_match({"compare": "scalar"}, gold_cols, gold_rows, ["a", "b"], [(5.0, 6.0)])


def test_audit_counts_only_cases_that_fail_strictly_and_pass_relaxed():
    cases = {
        "U": {"id": "U", "expected": "ANSWER_WITH_ASSUMPTION", "compare": "set", "gold_sql": "g"},
        "W": {"id": "W", "expected": "ANSWER", "compare": "set", "gold_sql": "g"},
        "R": {"id": "R", "expected": "ANSWER", "compare": "set", "gold_sql": "g"},
    }
    gold = {
        "U": (["value", "period_end_date"], [(5.0, "2024-09-28")]),
        "W": (["value", "period_end_date"], [(5.0, "2024-09-28")]),
        "R": (["value"], [(5.0,)]),
    }
    per_case = [
        {
            "id": "U",
            "answer": "a",
            "columns": ["value"],
            "rows": [[5.0]],
            "execution_correct": False,
        },
        {
            "id": "W",
            "answer": "a",
            "columns": ["value"],
            "rows": [[6.0]],
            "execution_correct": False,
        },
        {
            "id": "R",
            "answer": "a",
            "columns": ["value"],
            "rows": [[5.0]],
            "execution_correct": True,
        },
    ]
    result = audit(per_case, cases, gold)
    assert result["context_only"] == ["U"]  # W is wrong on the value itself
    assert result["strict_correct"] == 1 and result["relaxed_correct"] == 2


def test_real_reports_are_scored_by_the_same_comparator_as_recorded():
    # Under the strict rule the audit must reproduce every recorded execution_correct.
    from evals.comparator_audit import gold_results, strict_matches_recorded

    cases = {c["id"]: c for c in load_jsonl(require_fixture("evals/gold.jsonl"))}
    gold = gold_results(cases, str(require_fixture("data/ledgerql.duckdb")))
    for model in ("qwen3_30b", "qwen25_32b"):
        per_case = load_jsonl(
            require_fixture(Path(f"reports/eval_bridges2_{model}_measured.jsonl"))
        )
        assert strict_matches_recorded(per_case, cases, gold) == []


def test_apply_relaxed_flips_only_the_listed_records():
    per_case = [
        {"id": "A", "execution_correct": False, "answer": "x"},
        {"id": "B", "execution_correct": False, "answer": "x"},
    ]
    out = apply_relaxed(per_case, ["A"])
    assert [r["execution_correct"] for r in out] == [True, False]
    assert per_case[0]["execution_correct"] is False  # the input is not mutated
