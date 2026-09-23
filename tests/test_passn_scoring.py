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
