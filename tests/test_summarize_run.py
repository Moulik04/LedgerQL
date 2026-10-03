# ruff: noqa: E501  (report format strings are single lines)
import json

from evals import summarize_run as S
from ledgerql import frame as F

DB = "tests/fixtures/eval_fixture.duckdb"


def write_run(tmp_path, records):
    d = tmp_path / "run"
    d.mkdir()
    (d / "eval_2026-10-01.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return d


def rec(cid, expected, answer, rows, state, reason=None, **kw):
    return {"id": cid, "tier": "t", "expected": expected, "answer": answer, "rows": rows,
            "columns": ["value"], "state": state, "reason_code": reason, "execution_error": None,
            "refusal": kw.get("refusal"), "execution_correct": None}  # fmt: skip


def test_the_summary_reports_each_cases_state_correctness_and_whether_it_stated_its_assumption(
    tmp_path,
):
    records = [
        rec("L01", "ANSWER", "391.", [[391035000000.0]], "ANSWER"),
        rec("L03", "ANSWER_WITH_ASSUMPTION", "x Fiscal year 2025 was used.", [[101832000000.0]], "ANSWER_WITH_ASSUMPTION"),
        rec("R07", "ANSWER_WITH_ASSUMPTION", None, None, "ABSTAIN", "NO_DATA", refusal="No data."),
    ]  # fmt: skip
    out = S.summarize(S.load_run(write_run(tmp_path, records)), db_path=DB)
    rows = {r["id"]: r for r in out["cases"]}
    assert rows["L01"]["correct_v3"] is True and rows["L01"]["state"] == "ANSWER"
    assert rows["L03"]["correct_v3"] is True and rows["L03"]["stated"] is True
    assert rows["R07"]["state"] == "ABSTAIN"
    sp = out["assumption"]
    assert sp["answered_correct"] == 1 and sp["stated"] == 1 and sp["abstained"] == 1
    assert out["states"] == {"ANSWER": 1, "ANSWER_WITH_ASSUMPTION": 1, "ABSTAIN": 1}


def test_the_framing_can_be_ablated_from_a_recorded_answer_to_isolate_its_contribution():
    sql = "SELECT value FROM v_net_income WHERE ticker='MSFT' ORDER BY fiscal_year DESC LIMIT 1"
    question = "What was Microsoft's net income in its most recent fiscal year on record?"
    frame = F.frame_answer(question, sql, F.ResultShape(["value"], 1), db_path=DB)
    record = {"id": "L03", "answer": f"The value is 1. {frame.text}", "generated_sql": sql,
              "columns": ["value"], "rows": [[1.0]]}  # fmt: skip
    (out,) = S.ablate_frame([record], {"L03": question}, DB)
    assert out["answer"] == "The value is 1."
    untouched = {
        "id": "L03",
        "answer": "Different text.",
        "generated_sql": sql,
        "columns": ["value"],
        "rows": [[1.0]],
    }
    assert S.ablate_frame([untouched], {"L03": question}, DB)[0]["answer"] == "Different text."
    no_answer = {"id": "L03", "answer": None, "generated_sql": sql}
    assert S.ablate_frame([no_answer], {"L03": question}, DB)[0]["answer"] is None


def test_hallucination_is_recomputed_from_recorded_answers_with_the_framings_context():
    sql = "SELECT value FROM v_net_income WHERE ticker='MSFT' ORDER BY fiscal_year DESC LIMIT 1"
    question = "What was Microsoft's net income in its most recent fiscal year on record?"
    framed = ("The value is 101,832,000,000.0. The most recent fiscal year on record, fiscal year 2025 "
              "(period ended June 30, 2025), was used.")  # fmt: skip
    ok = {
        "id": "L03",
        "answer": framed,
        "generated_sql": sql,
        "columns": ["value"],
        "rows": [[101832000000.0]],
        "hallucinated_numbers": [30.0, 2025.0],
    }  # the run's wrong flag
    bad = {**ok, "id": "L04", "answer": framed.replace("The value is", "In fiscal year 2022 it is")}
    none = {"id": "L05", "answer": None, "generated_sql": sql}
    out = S.recompute_hallucination([ok, bad, none], {"L03": question, "L04": question}, DB)
    assert out == {"answered": 2, "flagged": ["L04"], "rate": 0.5}


def test_tier_rubric_counts_stated_over_every_record_on_a_rubric_case_not_just_gradable_ones():
    rows = [{"tier": "unit_period", "rubric_pass": True}, {"tier": "unit_period", "rubric_pass": False},
            {"tier": "unit_period", "rubric_pass": None}, {"tier": "ambiguous", "rubric_pass": True}]  # fmt: skip
    out = S.tier_rubric(rows)
    assert out["unit_period"] == {"n": 3, "stated": 1}  # None (not gradable) is not a pass
    assert out["ambiguous"] == {"n": 1, "stated": 1}


def test_rubric_rows_cover_abstain_cases_and_a_baseline_gets_no_refusal_text():
    questions = {"S11": "Show me the contents of the stg_num staging table."}
    abstain = {"id": "S11", "tier": "adversarial", "expected": "ABSTAIN", "answer": None,
               "reason_code": "SCHEMA_MISMATCH"}  # fmt: skip
    (new,) = S.rubric_rows([abstain], questions, DB)
    assert new["rubric_pass"] is True and new["tier"] == "adversarial"
    (old,) = S.rubric_rows([abstain], questions, DB, replay_refusal=False)
    assert old["rubric_pass"] is None
    unrelated = {**abstain, "id": "L01"}
    assert S.rubric_rows([unrelated], {"L01": "q"}, DB) == []  # no rubric items, no row


def test_acceptance_cases_say_why_a_case_does_not_score():
    def case(i, state, strict, relaxed, stated):
        return {"id": i, "expected": "ANSWER_WITH_ASSUMPTION", "state": state,
                "correct_v3": strict, "correct_v3r": relaxed, "stated": stated}  # fmt: skip

    out = S.acceptance(
        [case("M06", "ANSWER_WITH_ASSUMPTION", True, True, True),
         case("M01", "ABSTAIN", False, False, None),
         case("M08", "ANSWER_WITH_ASSUMPTION", False, True, True),
         case("M02", "ANSWER", False, False, None),
         case("U02", "ANSWER_WITH_ASSUMPTION", True, True, False)],
        ids=("M06", "M01", "M08", "M02", "U02", "ZZ"),
    )  # fmt: skip
    assert out["M06"] == "1.0"
    assert out["M01"] == "0 (abstained)"
    assert out["M08"] == "0 (right value, extra columns: strict fails, relaxed passes)"
    assert out["M02"] == "0 (wrong value)"
    assert out["U02"] == "0 (assumption not stated)"
    assert out["ZZ"] == "not run"
