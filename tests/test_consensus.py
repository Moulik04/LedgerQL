from ledgerql import consensus
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


def _guard(sql, ok=True, events=None, reason_code=None):
    return GuardrailResult(ok=ok, sql=sql, events=events or [], reason_code=reason_code)


def test_vote_unanimous_agreement():
    guards = [_guard("SELECT 1") for _ in range(5)]
    execs = [ExecutionResult(columns=["x"], rows=[(1,)]) for _ in range(5)]

    result = consensus.vote(guards, execs)

    assert result.agreement == 1.0
    assert result.columns == ["x"]
    assert result.rows == [(1,)]
    assert result.reason_code is None


def test_vote_majority_wins_agreement_fraction():
    guards = [_guard("SELECT 1") for _ in range(5)]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(2,)]),
        ExecutionResult(columns=["x"], rows=[(2,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.rows == [(1,)]
    assert result.agreement == 3 / 5


def test_vote_agreement_divides_by_total_n_not_just_survivors():
    # Only 2 of 5 candidates even produced a usable result, and both
    # agree with each other -- agreement must be 2/5, not 2/2, since a
    # low SQL-generation success rate is itself a low-confidence signal.
    guards = [
        _guard("SELECT 1"),
        _guard("SELECT 1"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
    ]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        None,
        None,
        None,
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 2 / 5
    assert result.reason_code is None  # a winner *was* found


def test_vote_ignores_executions_with_an_error():
    guards = [_guard("SELECT 1") for _ in range(3)]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(error="syntax error"),
        ExecutionResult(columns=["x"], rows=[(1,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 2 / 3
    assert result.rows == [(1,)]


def test_vote_row_order_insensitive_clustering():
    # Two candidates whose rows are the same set in a different physical
    # order (e.g. no explicit ORDER BY) must cluster together, not be
    # treated as disagreeing.
    guards = [_guard("SELECT 1"), _guard("SELECT 1")]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,), (2,)]),
        ExecutionResult(columns=["x"], rows=[(2,), (1,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 1.0


def test_vote_preserves_winner_original_row_order_in_output():
    # Clustering is order-insensitive, but the *returned* rows must keep
    # the winning candidate's own order (e.g. a real ORDER BY is
    # semantically meaningful and must not be scrambled).
    guards = [_guard("SELECT 1 ORDER BY x DESC") for _ in range(3)]
    execs = [ExecutionResult(columns=["x"], rows=[(2,), (1,)]) for _ in range(3)]

    result = consensus.vote(guards, execs)

    assert result.rows == [(2,), (1,)]


def test_vote_no_winner_uses_most_common_rejection_reason():
    guards = [
        _guard("bad1", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad2", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad3", ok=False, events=["cost_limit"], reason_code="COST_LIMIT"),
    ]
    execs = [None, None, None]

    result = consensus.vote(guards, execs)

    assert result.reason_code == "SCHEMA_MISMATCH"
    assert result.agreement == 0.0
    assert result.sql == "bad1"  # first rejected candidate, for audit visibility


def test_vote_no_winner_defaults_to_exec_error_when_no_rejection_reasons():
    # Every guard passed, but every execution errored -- there is no
    # guardrail rejection reason to take a mode of.
    guards = [_guard("SELECT 1") for _ in range(2)]
    execs = [ExecutionResult(error="timeout"), ExecutionResult(error="timeout")]

    result = consensus.vote(guards, execs)

    assert result.reason_code == "EXEC_ERROR"


def test_vote_exec_error_falls_back_to_a_passing_guards_sql_for_audit_trail():
    # No rejected guard exists (every guard passed) so there is no
    # rejected sql to show -- previously this left ConsensusResult.sql as
    # None, losing the audit trail of what was actually attempted. It
    # must fall back to the first passing guard's sql instead.
    guards = [_guard("SELECT 1 FROM missing_table"), _guard("SELECT 2 FROM missing_table")]
    execs = [ExecutionResult(error="timeout"), ExecutionResult(error="timeout")]

    result = consensus.vote(guards, execs)

    assert result.reason_code == "EXEC_ERROR"
    assert result.sql == "SELECT 1 FROM missing_table"


def test_vote_deduplicates_events_across_candidates():
    guards = [
        _guard("SELECT 1", events=["cost_limit"]),
        _guard("SELECT 1", events=["cost_limit"]),
    ]
    execs = [ExecutionResult(columns=["x"], rows=[(1,)]) for _ in range(2)]

    result = consensus.vote(guards, execs)

    assert result.events == ["cost_limit"]


def test_vote_winner_with_legitimately_empty_rows_is_not_a_no_winner_case():
    guards = [_guard("SELECT 1 WHERE 1=0") for _ in range(5)]
    execs = [ExecutionResult(columns=["x"], rows=[]) for _ in range(5)]

    result = consensus.vote(guards, execs)

    assert result.reason_code is None
    assert result.rows == []
    assert result.agreement == 1.0


def test_vote_clusters_by_row_values_not_column_names():
    # Real gold-set case (A01, "top 10 companies by revenue"): 4 of 5
    # candidates return the exact same top-10 companies/values but with
    # different column aliases (SUM(value) AS total_revenue vs. a bare
    # value) -- these must still cluster together as one 4/5 agreement,
    # not split into two 2/5 clusters just because the column label
    # differs. Only the actual row values are being grounded; column
    # names are never compared against anything downstream.
    guards = [_guard("SELECT 1") for _ in range(5)]
    same_values = [("WMT", 674538000000.0), ("AMZN", 637959000000.0)]
    execs = [
        ExecutionResult(columns=["ticker", "total_revenue"], rows=same_values),
        ExecutionResult(columns=["ticker", "value"], rows=same_values),
        ExecutionResult(columns=["ticker", "total_revenue"], rows=same_values),
        ExecutionResult(columns=["ticker", "value"], rows=same_values),
        ExecutionResult(
            columns=["ticker", "name", "value"], rows=[("WMT", "Walmart", 674538000000.0)]
        ),
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 4 / 5
    assert result.rows == same_values
