from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import pipeline
from ledgerql.classify import ClassifyResult
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


def _patch_audit(monkeypatch):
    records = []
    monkeypatch.setattr(audit_module, "write_record", lambda r: records.append(r) or "fake-id")
    return records


def test_ask_short_circuits_on_classify_out_of_scope(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module,
        "classify",
        lambda q: ClassifyResult(verdict="OUT_OF_SCOPE", explanation="e"),
    )
    calls = []
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda *a, **k: calls.append(1) or ["SELECT 1"]
    )

    result = pipeline.ask("Should I buy Tesla stock?")

    assert result["answer"] is None
    assert result["reason_code"] == "OUT_OF_SCOPE"
    assert result["sql"] is None
    assert calls == []  # generation never ran
    assert len(records) == 1
    assert records[0]["reason_code"] == "OUT_OF_SCOPE"


def test_ask_short_circuits_on_classify_schema_mismatch(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module,
        "classify",
        lambda q: ClassifyResult(verdict="SCHEMA_MISMATCH", explanation="e"),
    )

    result = pipeline.ask("What was Apple's dividend yield?")

    assert result["answer"] is None
    assert result["reason_code"] == "SCHEMA_MISMATCH"
    assert len(records) == 1


def test_ask_short_circuits_on_guardrail_rejection(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda q, s, n=1: ["DELETE FROM filings"]
    )
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: GuardrailResult(
            ok=False,
            sql=sql,
            events=["read_only"],
            reason_code="OUT_OF_SCOPE",
            detail="not a SELECT",
        ),
    )
    exec_calls = []
    monkeypatch.setattr(execute_module, "execute", lambda *a, **k: exec_calls.append(1))

    result = pipeline.ask("Delete all filings for Tesla.")

    assert result["answer"] is None
    assert result["reason_code"] == "OUT_OF_SCOPE"
    assert result["guardrail_events"] == ["read_only"]
    assert exec_calls == []  # execution never ran
    assert len(records) == 1
    assert records[0]["guardrail_events"] == ["read_only"]


def test_ask_returns_exec_error_reason_code(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["SELECT bad"])
    monkeypatch.setattr(
        guardrails_module, "validate", lambda sql, db_path=None: GuardrailResult(ok=True, sql=sql)
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql, db_path=None: ExecutionResult(error="syntax error")
    )
    answer_calls = []
    monkeypatch.setattr(answer_module, "write_answer", lambda *a, **k: answer_calls.append(1))

    result = pipeline.ask("q")

    assert result["error"] == "syntax error"
    assert result["answer"] is None
    assert result["reason_code"] == "EXEC_ERROR"
    assert answer_calls == []
    assert len(records) == 1


def test_ask_returns_full_success_result(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )
    captured = {}

    def fake_generate(question, schema_context, n=1):
        captured["schema_context"] = schema_context
        return ["SELECT 1"]

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: GuardrailResult(ok=True, sql="SELECT 1"),
    )
    monkeypatch.setattr(
        execute_module,
        "execute",
        lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)]),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "The value is 1.")

    result = pipeline.ask("what is 1?")

    assert result["question"] == "what is 1?"
    assert result["sql"] == "SELECT 1"
    assert result["columns"] == ["x"]
    assert result["rows"] == [(1,)]
    assert result["error"] is None
    assert result["answer"] == "The value is 1."
    assert result["reason_code"] is None
    assert len(records) == 1
    assert records[0]["answer"] == "The value is 1."
    assert records[0]["confidence"] is None
    # schema_index is unmocked in this test, so generate_candidates should
    # receive the real schema context (not a stub) -- v_revenue is one of
    # the Concept view sections docs/schema.md always defines.
    assert "v_revenue" in captured["schema_context"]


def test_ask_writes_audit_record_and_does_not_raise_on_classify_crash(monkeypatch):
    records = _patch_audit(monkeypatch)

    def _boom(q):
        raise Exception("boom")

    monkeypatch.setattr(classify_module, "classify", _boom)

    result = pipeline.ask("Should I buy Tesla stock?")

    assert result["reason_code"] == "EXEC_ERROR"
    assert result["error"] == "boom"
    assert result["answer"] is None
    assert len(records) == 1
    assert records[0]["reason_code"] == "EXEC_ERROR"


def test_ask_threads_db_path_to_guardrails_and_execute(monkeypatch):
    _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["SELECT 1"])
    captured = {}

    def fake_validate(sql, db_path=None):
        captured["guardrail_db_path"] = db_path
        return GuardrailResult(ok=True, sql=sql)

    def fake_execute(sql, db_path=None):
        captured["execute_db_path"] = db_path
        return ExecutionResult(columns=["x"], rows=[(1,)])

    monkeypatch.setattr(guardrails_module, "validate", fake_validate)
    monkeypatch.setattr(execute_module, "execute", fake_execute)
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "answer")

    pipeline.ask("q", db_path="custom.duckdb")

    assert captured["guardrail_db_path"] == "custom.duckdb"
    assert captured["execute_db_path"] == "custom.duckdb"
