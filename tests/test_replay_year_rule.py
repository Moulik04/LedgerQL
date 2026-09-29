from pathlib import Path

from evals.passn_scoring import load_jsonl
from evals.replay_repair_off import revert_exec_error_repairs
from evals.replay_year_rule import apply_year_rule, year_rule_flags
from evals.year_audit import audit
from tests.support import require_fixture


def _rec(id_, answer, columns, rows, sql, expected="ANSWER", correct=True):
    return {
        "id": id_,
        "expected": expected,
        "answer": answer,
        "columns": columns,
        "rows": rows,
        "generated_sql": sql,
        "reason_code": None,
        "confidence": 1.0,
        "repair": None,
        "execution_correct": correct,
        "hallucinated_numbers": [],
    }


BARE = "SELECT value FROM v_revenue WHERE fiscal_year = 2025"


def test_an_answer_with_an_invented_year_becomes_an_ungrounded_abstain():
    rec = _rec("A", "5.0 for fiscal year 2022.", ["value"], [[5.0]], BARE)
    [out] = apply_year_rule([rec])
    assert out["answer"] is None and out["reason_code"] == "UNGROUNDED_ANSWER"
    assert out["rows"] == [] and out["columns"] == []
    # An ANSWER-expected case that abstains is no longer execution-correct.
    assert out["execution_correct"] is False
    assert "hallucinated_numbers" not in out


def test_a_year_grounded_by_the_sql_filter_is_left_alone():
    rec = _rec("A", "5.0 for fiscal year 2025.", ["value"], [[5.0]], BARE)
    assert apply_year_rule([rec]) == [rec]


def test_an_abstain_expected_answer_loses_execution_correct_the_way_revert_does():
    rec = _rec("A", "As of 2022.", ["value"], [[5.0]], BARE, expected="ABSTAIN")
    [out] = apply_year_rule([rec])
    assert out["answer"] is None and "execution_correct" not in out


def test_abstained_records_pass_through_untouched():
    rec = {**_rec("A", None, [], [], None), "reason_code": "LOW_AGREEMENT"}
    assert apply_year_rule([rec]) == [rec]


def test_year_rule_flags_lists_exactly_the_answers_it_would_abstain():
    good = _rec("G", "5.0 for 2025.", ["value"], [[5.0]], BARE)
    bad = _rec("B", "5.0 for 2022.", ["value"], [[5.0]], BARE)
    assert year_rule_flags([good, bad]) == ["B"]


def test_on_the_real_runs_the_rule_flags_the_30bs_17_and_none_of_the_32bs():
    def flags_and_audit(model):
        path = require_fixture(Path(f"reports/eval_bridges2_{model}_measured.jsonl"))
        shipped = revert_exec_error_repairs(load_jsonl(path))
        return year_rule_flags(shipped), sorted(f["id"] for f in audit(shipped)["ungrounded"])

    flags, found = flags_and_audit("qwen3_30b")
    assert flags == found and len(flags) == 17  # none of the 17 is grounded by the SQL either
    flags, found = flags_and_audit("qwen25_32b")
    # T03 states years in no result cell, but they are the SQL's own filter years:
    # the audit counts it, the rule (result cell OR SQL literal) rightly passes it.
    assert found == ["T03"] and flags == []
