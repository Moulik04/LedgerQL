import duckdb

from evals.passn_scoring import compute_pass_at_n


def _make_companies_db(tmp_path, rows):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE companies (cik INTEGER, revenue INTEGER)")
    for cik, revenue in rows:
        con.execute("INSERT INTO companies VALUES (?, ?)", [cik, revenue])
    con.close()
    return str(db_path)


CASES = {
    "A1": {
        "id": "A1",
        "tier": "lookup",
        "expected": "ANSWER",
        "gold_sql": "SELECT revenue FROM companies WHERE cik = 1",
        "compare": "scalar",
    },
}


def test_pass_at_n_true_when_a_non_winning_candidate_matches_gold(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 999)])
    per_case = [
        {
            "id": "A1",
            "answer": "wrong",
            "execution_correct": False,  # the winner (candidate 0) was wrong
            "candidates": [
                {"sql": "SELECT revenue FROM companies WHERE cik = 2"},  # wrong, this is the winner
                {"sql": "SELECT revenue FROM companies WHERE cik = 1"},  # right, but not selected
            ],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_at_1"] == 0.0
    assert stats["overall"]["pass_at_n"] == 1.0
    assert stats["overall"]["gap"] == 1.0
    assert stats["by_tier"]["lookup"]["pass_at_1"] == 0.0
    assert stats["by_tier"]["lookup"]["pass_at_n"] == 1.0


def test_pass_at_n_false_when_no_candidate_matches_gold(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 999)])
    per_case = [
        {
            "id": "A1",
            "answer": "wrong",
            "execution_correct": False,
            "candidates": [
                {"sql": "SELECT revenue FROM companies WHERE cik = 2"},
                {"sql": "SELECT revenue FROM companies WHERE cik = 2"},
            ],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_at_1"] == 0.0
    assert stats["overall"]["pass_at_n"] == 0.0


def test_unparseable_candidate_sql_does_not_crash_and_does_not_count(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100)])
    per_case = [
        {
            "id": "A1",
            "answer": None,
            "execution_correct": False,
            "candidates": [
                {"sql": "NOT VALID SQL AT ALL((("},
                {"sql": "SELECT revenue FROM companies WHERE cik = 1"},
            ],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_at_n"] == 1.0  # the second candidate still counts


def test_missing_candidates_key_counts_as_no_pass(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100)])
    per_case = [{"id": "A1", "answer": None, "execution_correct": False}]  # e.g. a crash record
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_at_1"] == 0.0
    assert stats["overall"]["pass_at_n"] == 0.0


def test_handles_zero_answer_cases(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100)])
    stats = compute_pass_at_n([], {}, db_path)
    assert stats["overall"]["pass_at_1"] == 0.0
    assert stats["overall"]["pass_at_n"] == 0.0
    assert stats["by_tier"] == {}


import pytest  # noqa: E402

from evals.passn_scoring import PassNInvariantError, assert_winner_implies_candidate  # noqa: E402
from ledgerql import execute, guardrails  # noqa: E402

GOOD = "SELECT revenue FROM companies WHERE cik = 1"
BAD = "SELECT revenue FROM companies WHERE cik = 2"


def test_pass_at_1_is_recomputed_locally_from_the_winner_not_the_recorded_score(tmp_path):
    # The vote picked the right query, then a later gate (verifier) withheld
    # the answer, so the recorded score says wrong. Selection was right.
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 999)])
    winner_sql = guardrails.validate(GOOD, db_path=db_path).sql
    per_case = [
        {
            "id": "A1",
            "answer": None,
            "reason_code": "UNGROUNDED_ANSWER",
            "execution_correct": False,
            "generated_sql": winner_sql,
            "candidates": [{"sql": GOOD}, {"sql": BAD}],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_1"] == 1
    assert stats["overall"]["pass_n"] == 1
    assert [d["cause"] for d in stats["drift"]] == ["post_vote_gate"]


def test_a_repair_winner_outside_the_candidate_pool_is_not_pass_at_1(tmp_path):
    # A repaired SQL is not one of the N sampled candidates, so it cannot
    # count toward pass@1 of the N; it is reported separately.
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 999)])
    per_case = [
        {
            "id": "A1",
            "answer": "x",
            "execution_correct": True,
            "generated_sql": GOOD,
            "repair": {"trigger": "exec_error", "sql": GOOD},
            "candidates": [{"sql": BAD}, {"sql": "NOT SQL((("}],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    assert stats["overall"]["pass_1"] == 0
    assert stats["overall"]["pass_n"] == 0
    assert stats["overall"]["winner_outside_pool_correct"] == 1
    assert [d["cause"] for d in stats["drift"]] == ["repair_rescue"]


def test_pass_at_n_never_below_pass_at_1_on_any_tier(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 999)])
    winner_sql = guardrails.validate(GOOD, db_path=db_path).sql
    per_case = [
        {
            "id": "A1",
            "answer": "x",
            "execution_correct": True,
            "generated_sql": winner_sql,
            "candidates": [{"sql": GOOD}, {"sql": BAD}],
        }
    ]
    stats = compute_pass_at_n(per_case, CASES, db_path)
    for bucket in [stats["overall"], *stats["by_tier"].values()]:
        assert bucket["pass_n"] >= bucket["pass_1"]


def test_planted_violation_fails_loudly():
    with pytest.raises(PassNInvariantError, match="A1"):
        assert_winner_implies_candidate("A1", winner_correct=True, any_candidate_correct=False)
    assert_winner_implies_candidate("A1", winner_correct=True, any_candidate_correct=True)
    assert_winner_implies_candidate("A1", winner_correct=False, any_candidate_correct=False)


def test_recorded_rows_that_differ_from_local_reexecution_are_reported_as_db_drift(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100)])
    winner_sql = guardrails.validate(GOOD, db_path=db_path).sql
    base = {
        "answer": "x",
        "reason_code": None,
        "execution_correct": True,
        "generated_sql": winner_sql,
        "candidates": [{"sql": GOOD}],
    }
    same = {**base, "id": "A1", "rows": [[100]]}
    stats = compute_pass_at_n([same], CASES, db_path)
    assert stats["rows_drift"] == []
    drifted = {**base, "id": "A1", "rows": [[101]]}
    stats = compute_pass_at_n([drifted], CASES, db_path)
    assert stats["rows_drift"] == ["A1"]


def test_missing_database_path_errors_and_does_not_create_a_file(tmp_path):
    missing = tmp_path / "nope.duckdb"
    with pytest.raises(Exception):  # noqa: B017 - duckdb raises its own IOException
        compute_pass_at_n([], {}, str(missing))
    assert not missing.exists()


def test_unordered_result_with_same_rows_in_a_different_order_is_not_db_drift(tmp_path):
    db_path = _make_companies_db(tmp_path, [(1, 100), (2, 200)])
    sql = "SELECT revenue FROM companies WHERE revenue > 0"
    winner_sql = guardrails.validate(sql, db_path=db_path).sql
    local = [list(r) for r in execute.execute(winner_sql, db_path=db_path).rows]
    record = {
        "id": "A1",
        "answer": "x",
        "reason_code": None,
        "execution_correct": False,
        "generated_sql": winner_sql,
        "candidates": [{"sql": sql}],
        "rows": list(reversed(local)),
    }
    assert compute_pass_at_n([record], CASES, db_path)["rows_drift"] == []
    # positive control: same setup, different values, must be flagged.
    changed = {**record, "rows": [[999], [200]]}
    assert compute_pass_at_n([changed], CASES, db_path)["rows_drift"] == ["A1"]
