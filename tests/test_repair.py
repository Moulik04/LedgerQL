from ledgerql import repair
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


def _failed(sql, reason_code, detail="boom", events=None):
    return GuardrailResult(
        ok=False, sql=sql, events=events or [], reason_code=reason_code, detail=detail
    )


def test_exec_error_with_no_usable_cluster_triggers_a_repair():
    guards = [_failed("SELEC 1", "EXEC_ERROR")] * 5
    assert repair.failure_trigger("EXEC_ERROR", guards) == "exec_error"


def test_schema_mismatch_on_a_stray_column_triggers_a_repair():
    sql = "SELECT dividend_yield FROM v_revenue WHERE ticker = 'AAPL'"
    guards = [_failed(sql, "SCHEMA_MISMATCH", events=["schema_allowlist"])] * 5
    assert (
        repair.failure_trigger("SCHEMA_MISMATCH", guards, enabled=repair.TRIGGERS)
        == "schema_mismatch"
    )


def test_a_stray_table_is_never_repaired_even_though_it_is_schema_mismatch():
    # S07/S11: "list every table in information_schema" is a correct hard
    # refusal. Repairing it would just rewrite the request into an allowed
    # query and answer a schema-snooping question.
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    guards = [_failed(sql, "SCHEMA_MISMATCH", events=["schema_allowlist"])] * 5
    assert repair.failure_trigger("SCHEMA_MISMATCH", guards, enabled=repair.TRIGGERS) is None


def test_one_stray_table_among_repairable_candidates_blocks_repair():
    bad = "SELECT * FROM stg_num WHERE 1 = 1"
    ok_col = "SELECT nope FROM v_revenue WHERE ticker = 'AAPL'"
    guards = [_failed(ok_col, "SCHEMA_MISMATCH")] * 4 + [_failed(bad, "SCHEMA_MISMATCH")]
    assert repair.failure_trigger("SCHEMA_MISMATCH", guards, enabled=repair.TRIGGERS) is None


def test_deliberate_refusals_are_never_repaired():
    guards = [_failed("DELETE FROM filings", "OUT_OF_SCOPE", events=["read_only"])] * 5
    assert repair.failure_trigger("OUT_OF_SCOPE", guards) is None
    assert repair.failure_trigger("COST_LIMIT", guards) is None
    assert repair.failure_trigger(None, guards) is None


def test_feedback_prefers_the_first_guardrail_rejection():
    guards = [
        GuardrailResult(ok=True, sql="SELECT 1"),
        _failed("SELECT x", "EXEC_ERROR", "bad col"),
    ]
    execs = [ExecutionResult(columns=["a"], rows=[(1,)]), None]
    assert repair.failure_feedback(guards, execs) == ("SELECT x", "bad col")


def test_feedback_falls_back_to_the_first_execution_error():
    guards = [GuardrailResult(ok=True, sql="SELECT 1 / 0")] * 2
    execs = [ExecutionResult(error="division by zero"), ExecutionResult(error="other")]
    assert repair.failure_feedback(guards, execs) == ("SELECT 1 / 0", "division by zero")


def test_is_unchanged_ignores_case_whitespace_and_trailing_semicolon():
    a = "SELECT value FROM v_revenue WHERE ticker = 'X'"
    assert repair.is_unchanged(a, "select   value\nFROM v_revenue WHERE ticker = 'X' ;") is True
    assert repair.is_unchanged(a, "SELECT value FROM v_revenue WHERE ticker = 'Y'") is False


def test_only_exec_error_is_enabled_by_default():
    # schema_mismatch is built and tested but disabled for the Bridges-2
    # measurement: "repair on exec_error only".
    sql = "SELECT nope FROM v_revenue WHERE ticker = 'AAPL'"
    stray_column = [_failed(sql, "SCHEMA_MISMATCH")] * 5
    assert repair.failure_trigger("SCHEMA_MISMATCH", stray_column) is None
    assert repair.failure_trigger("EXEC_ERROR", [_failed("SELEC 1", "EXEC_ERROR")] * 5) == (
        "exec_error"
    )


def test_there_is_no_repair_trigger_for_an_empty_result():
    # Rejected design (DECISIONS.md): an empty result carries no error to feed
    # back. Only failures that carry a message are repair triggers.
    assert set(repair.TRIGGERS) == {"exec_error", "schema_mismatch"}
