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
