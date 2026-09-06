import duckdb

from ledgerql import execute


def _make_db(tmp_path, rows):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    con.close()
    return str(db_path)


def test_execute_returns_columns_and_rows(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x"), (2, "y")])
    result = execute.execute("SELECT a, b FROM t ORDER BY a", db_path=db_path)
    assert result.error is None
    assert result.columns == ["a", "b"]
    assert result.rows == [(1, "x"), (2, "y")]
    assert result.truncated is False


def test_execute_rejects_write_statements(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x")])
    result = execute.execute("DELETE FROM t", db_path=db_path)
    assert result.error is not None
    assert "read-only mode" in result.error


def test_execute_truncates_to_row_limit(tmp_path):
    db_path = _make_db(tmp_path, [(i, str(i)) for i in range(10)])
    result = execute.execute("SELECT a FROM t ORDER BY a", db_path=db_path, row_limit=3)
    assert result.error is None
    assert result.rows == [(0,), (1,), (2,)]
    assert result.truncated is True


def test_execute_does_not_flag_truncation_when_under_limit(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x"), (2, "y")])
    result = execute.execute("SELECT a FROM t", db_path=db_path, row_limit=1000)
    assert result.truncated is False


def test_execute_reports_syntax_errors(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x")])
    result = execute.execute("NOT VALID SQL AT ALL", db_path=db_path)
    assert result.error is not None
    assert result.rows == []


def test_execute_times_out_on_slow_query(tmp_path):
    db_path = tmp_path / "slow.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (a INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(900)])
    con.close()

    result = execute.execute(
        "SELECT SUM(a.a * b.a * c.a) FROM t a, t b, t c",
        db_path=str(db_path),
        timeout_seconds=0.3,
    )
    assert result.error is not None
    assert "timed out" in result.error.lower()
