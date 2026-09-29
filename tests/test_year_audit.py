from pathlib import Path

from evals.year_audit import (
    audit,
    audit_record,
    excluded_tokens,
    form_codes_ungrounded,
    load_jsonl,
    result_years,
)
from tests.support import require_fixture


def _rec(answer, columns, rows, **kw):
    return {"id": "X", "answer": answer, "columns": columns, "rows": rows, **kw}


def test_result_years_reads_ints_floats_and_year_prefixed_date_strings():
    years = result_years(
        ["fy", "d", "v"], [[2024, "2024-09-28", 391035000000.0], [2023.0, "n/a", 5]]
    )
    assert years == {2023, 2024}


def test_a_year_in_prose_that_the_result_does_not_contain_is_flagged():
    # U02's shape: the result held only a value, the prose named a year.
    finding = audit_record(
        _rec("It is 391,035,000,000.0 for fiscal year 2022.", ["value"], [[3.9e11]])
    )
    assert finding["ungrounded_years"] == [2022]
    assert finding["verifier_covers"] is False  # no fiscal_year column, so verify.py never looks


def test_a_year_the_result_contains_is_not_flagged_including_via_a_date_cell():
    assert not audit_record(_rec("Ended 2024.", ["d"], [["2024-09-28"]]))["ungrounded_years"]
    assert not audit_record(_rec("Fiscal 2024.", ["fiscal_year"], [[2024]]))["ungrounded_years"]


def test_a_wrong_year_with_a_fiscal_year_column_is_one_the_verifier_already_covers():
    finding = audit_record(_rec("Fiscal 2022.", ["fiscal_year", "value"], [[2024, 1.0]]))
    assert finding["ungrounded_years"] == [2022] and finding["verifier_covers"] is True


def test_prose_without_a_year_has_nothing_to_flag():
    finding = audit_record(_rec("The value is 5.", ["v"], [[5]]))
    assert finding["prose_years"] == [] and finding["ungrounded_years"] == []


def test_excluded_tokens_names_each_class_verify_skips():
    found = excluded_tokens("Filed a 10-K in 2024 and a 10-Q in 2023.")
    assert set(found) == {("form_code", "10"), ("year", "2024"), ("year", "2023")}
    assert excluded_tokens("The value is 391,035,000,000.0.") == []


def test_audit_counts_only_answered_cases_and_splits_by_correctness():
    per_case = [
        {**_rec("FY 2022.", ["value"], [[1.0]], execution_correct=True), "id": "A"},
        {**_rec("FY 2022.", ["value"], [[1.0]], execution_correct=False), "id": "B"},
        {**_rec("FY 2024.", ["fiscal_year"], [[2024]], execution_correct=True), "id": "C"},
        {**_rec(None, [], [], execution_correct=False), "id": "D"},  # abstained
    ]
    summary = audit(per_case)
    assert summary["answered"] == 3
    assert summary["with_year_in_prose"] == 3
    assert [f["id"] for f in summary["ungrounded"]] == ["A", "B"]
    assert summary["ungrounded_correct"] == 1 and summary["ungrounded_wrong"] == 1


def test_real_reports_hold_the_counts_the_decision_records():
    for model in ("qwen3_30b", "qwen25_32b"):
        report = require_fixture(Path(f"reports/eval_bridges2_{model}_measured.jsonl"))
        summary = audit(load_jsonl(report))
        assert summary["answered"] > 0
        # every finding is an answer the recorded hallucinated_numbers field passed
        assert all(f["hallucinated_numbers"] == [] for f in summary["ungrounded"])


def test_an_ungrounded_year_is_classified_by_whether_the_question_asked_for_it():
    cases = {
        "A": {"question": "What was revenue in fiscal year 2025?"},
        "B": {"question": "What was revenue in fiscal year 2025?"},
    }
    per_case = [
        {**_rec("For fiscal year 2025.", ["value"], [[1.0]], execution_correct=True), "id": "A"},
        {**_rec("For fiscal year 2022.", ["value"], [[1.0]], execution_correct=True), "id": "B"},
    ]
    s = audit(per_case, cases)
    status = {f["id"]: f["year_status"] for f in s["ungrounded"]}
    # Right year but nothing shown supports it, versus a year the question never asked for.
    assert status == {"A": "asked_for_but_ungrounded", "B": "not_asked_for"}
    assert s["not_asked_for"] == 1


def test_form_codes_are_only_flagged_when_absent_from_the_result_text():
    assert form_codes_ungrounded("Filed a 10-K.", ["form"], [["10-K"]]) == []
    assert form_codes_ungrounded("Filed a 10-K.", ["v"], [[1]]) == ["10"]
