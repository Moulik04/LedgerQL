from ledgerql import answer as answer_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import pipeline
from ledgerql.execute import ExecutionResult


def test_ask_orchestrates_generate_execute_answer(monkeypatch):
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["SELECT 1"])
    monkeypatch.setattr(
        execute_module, "execute", lambda sql: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "The value is 1.")

    result = pipeline.ask("what is 1?")

    assert result["question"] == "what is 1?"
    assert result["sql"] == "SELECT 1"
    assert result["columns"] == ["x"]
    assert result["rows"] == [(1,)]
    assert result["truncated"] is False
    assert result["error"] is None
    assert result["answer"] == "The value is 1."


def test_ask_skips_answer_generation_on_execution_error(monkeypatch):
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["BAD SQL"])
    monkeypatch.setattr(
        execute_module, "execute", lambda sql: ExecutionResult(error="syntax error")
    )
    calls = []
    monkeypatch.setattr(
        answer_module, "write_answer", lambda q, r: calls.append(1) or "should not be called"
    )

    result = pipeline.ask("bad question")

    assert result["error"] == "syntax error"
    assert result["answer"] is None
    assert calls == []


def test_ask_threads_db_path_to_execute(monkeypatch):
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["SELECT 1"])
    calls = []

    def fake_execute(sql, **kwargs):
        calls.append(kwargs)
        return ExecutionResult(columns=["x"], rows=[(1,)])

    monkeypatch.setattr(execute_module, "execute", fake_execute)
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "The value is 1.")

    pipeline.ask("what is 1?", db_path="custom.duckdb")

    assert calls == [{"db_path": "custom.duckdb"}]


def test_ask_uses_real_schema_context(monkeypatch):
    captured = {}

    def fake_generate(question, schema_context, n=1):
        captured["schema_context"] = schema_context
        return ["SELECT 1"]

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        execute_module, "execute", lambda sql: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "answer")

    pipeline.ask("any question")

    assert "v_revenue" in captured["schema_context"]
