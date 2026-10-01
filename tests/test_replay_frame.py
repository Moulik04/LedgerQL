from evals import replay_frame as RF

DB = "tests/fixtures/eval_fixture.duckdb"


def rec(cid, sql, answer="The value is 1.", rows=((1.0,),), columns=("value",), ok=True):
    return {"id": cid, "answer": answer, "generated_sql": sql, "rows": [list(r) for r in rows],
            "columns": list(columns), "expected": "ANSWER_WITH_ASSUMPTION", "execution_error": None,
            "reason_code": None}  # fmt: skip


def test_the_framing_alone_is_graded_against_the_cases_rubric_items():
    q = {"L03": "What was Microsoft's net income in its most recent fiscal year on record?"}
    sql = "SELECT value FROM v_net_income WHERE ticker='MSFT' ORDER BY fiscal_year DESC LIMIT 1"
    (row,) = RF.replay([rec("L03", sql)], q, db_path=DB)
    assert row["frame_stated"] is True and "fiscal year 2025" in row["frame"]


def test_a_case_whose_items_the_framing_cannot_state_is_not_stated():
    q = {"A10": "What percentage of companies appear in the revenue view?"}
    (row,) = RF.replay([rec("A10", "SELECT 94.6")], q, db_path=DB)
    assert row["frame_stated"] is False  # nothing assumed, nothing stated


def test_records_without_an_answer_or_a_sql_or_rubric_items_are_skipped():
    q = {"L03": "q", "L01": "q"}
    assert RF.replay([{**rec("L03", "SELECT 1"), "answer": None}], q, db_path=DB) == []
    assert RF.replay([rec("L01", "SELECT 1")], q, db_path=DB) == []  # L01 has no rubric items
