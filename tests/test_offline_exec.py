import pytest

from evals import offline_exec as O
from ledgerql import execute

DB = "tests/fixtures/eval_fixture.duckdb"


def scripted(*outcomes):
    """A runner that returns the given outcomes in order, one per attempt."""
    calls = iter(outcomes)

    def runner(sql, db, timeout):
        return next(calls)

    return runner


def test_the_offline_timeout_is_far_above_the_live_pipelines():
    assert O.OFFLINE_TIMEOUT_SECONDS >= 12 * execute.QUERY_TIMEOUT_SECONDS


def test_a_query_that_runs_is_ok_on_the_first_attempt():
    out = O.run_candidate("q", DB, runner=scripted(O.Outcome("ok", "q", [(1,)], ["a"])))
    assert (out.status, out.attempts, out.rows) == ("ok", 1, [(1,)])


def test_a_timeout_is_retried_and_a_later_success_resolves_it():
    out = O.run_candidate(
        "q",
        DB,
        runner=scripted(
            O.Outcome("timeout", error="query timed out"), O.Outcome("ok", "q", [], [])
        ),
    )
    assert out.status == "ok" and out.attempts == 2


def test_a_timeout_on_every_attempt_stays_a_timeout_and_is_not_wrong():
    t = O.Outcome("timeout", error="query timed out after 120s")
    out = O.run_candidate("q", DB, runner=scripted(t, t, t))
    assert out.status == "timeout" and out.attempts == O.ATTEMPTS
    with pytest.raises(O.ScoringIncomplete, match="timeout after 3 attempts"):
        O.require_resolved({"A#0": out})


def test_a_real_sql_error_repeats_identically_and_is_an_error_not_a_timeout():
    e = O.Outcome("error", error="Binder Error: no such column")
    out = O.run_candidate("q", DB, runner=scripted(e, e, e))
    assert out.status == "error"
    O.require_resolved({"A#0": out})  # a deterministic error is a legitimate "wrong"


def test_failures_that_differ_between_attempts_are_unstable_and_fail_loudly():
    out = O.run_candidate(
        "q",
        DB,
        runner=scripted(
            O.Outcome("error", error="IO Error: lock"),
            O.Outcome("timeout", error="query timed out"),
            O.Outcome("error", error="IO Error: lock"),
        ),
    )
    assert out.status == "unstable"
    with pytest.raises(O.ScoringIncomplete, match="unstable"):
        O.require_resolved({"A#0": out})


def test_a_guard_rejection_is_final_and_not_retried():
    calls = []

    def runner(sql, db, timeout):
        calls.append(1)
        return O.Outcome("guard_rejected")

    assert O.run_candidate("DROP TABLE x", DB, runner=runner).status == "guard_rejected"
    assert len(calls) == 1


def test_the_execute_layer_reports_a_timeout_in_the_text_this_module_recognises(monkeypatch):
    res = execute.execute("SELECT count(*) FROM range(100000000000)", DB, timeout_seconds=0.05)
    assert res.error is not None and res.error.startswith(O._TIMEOUT_PREFIX)
    # ...and _attempt classifies exactly that result as a timeout, not as a wrong answer.
    monkeypatch.setattr(O.execute_module, "execute", lambda *a, **k: res)
    assert O._attempt("SELECT ticker FROM companies LIMIT 1", DB, 0.05).status == "timeout"


def test_the_real_runner_distinguishes_ok_guard_and_error():
    assert O.run_candidate("SELECT ticker FROM companies LIMIT 1", DB).status == "ok"
    assert O.run_candidate("DROP TABLE companies", DB).status == "guard_rejected"
    bad = O.run_candidate("SELECT CAST(name AS INTEGER) FROM companies LIMIT 1", DB)
    assert bad.status == "error" and "Conversion Error" in bad.error
