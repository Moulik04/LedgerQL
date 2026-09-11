from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import consensus as consensus_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import pipeline
from ledgerql import verify as verify_module
from ledgerql.classify import ClassifyResult
from ledgerql.consensus import ConsensusResult
from ledgerql.execute import ExecutionResult
from ledgerql.verify import VerifyResult


def _patch_audit(monkeypatch):
    records = []
    monkeypatch.setattr(audit_module, "write_record", lambda r: records.append(r) or "fake-id")
    return records


def _patch_classify_in_scope(monkeypatch):
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )


def _patch_generate(monkeypatch, sqls=None):
    sqls = sqls or ["SELECT 1"] * pipeline.N_CANDIDATES
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda q, s, n=1, temperature=None: sqls
    )


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
    assert result["confidence"] is None
    assert calls == []  # generation never ran
    assert len(records) == 1


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


def test_ask_generates_n_candidates(monkeypatch):
    _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    captured = {}

    def fake_generate(question, schema_context, n=1, temperature=None):
        captured["n"] = n
        captured["temperature"] = temperature
        return ["SELECT 1"] * n

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql),
    )
    monkeypatch.setattr(
        execute_module,
        "execute",
        lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)]),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 1.")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    pipeline.ask("q")

    assert captured["n"] == pipeline.N_CANDIDATES
    assert captured["temperature"] == generate_module.OLLAMA_CONSENSUS_TEMPERATURE


def test_ask_short_circuits_on_no_consensus_winner(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch, sqls=["DELETE FROM filings"] * pipeline.N_CANDIDATES)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(
            ok=False,
            sql=sql,
            events=["read_only"],
            reason_code="OUT_OF_SCOPE",
            detail="not a SELECT",
        ),
    )
    exec_calls = []
    monkeypatch.setattr(execute_module, "execute", lambda *a, **k: exec_calls.append(1))
    answer_calls = []
    monkeypatch.setattr(answer_module, "write_answer", lambda *a, **k: answer_calls.append(1))

    result = pipeline.ask("Delete all filings for Tesla.")

    assert result["answer"] is None
    assert result["reason_code"] == "OUT_OF_SCOPE"
    assert result["guardrail_events"] == ["read_only"]
    assert exec_calls == []  # every candidate rejected, execution never ran
    assert answer_calls == []
    assert len(records) == 1


def test_ask_abstains_on_low_agreement(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql),
    )
    monkeypatch.setattr(
        execute_module,
        "execute",
        lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)]),
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=0.2, reason_code=None
        ),
    )
    answer_calls = []
    monkeypatch.setattr(answer_module, "write_answer", lambda *a, **k: answer_calls.append(1))

    result = pipeline.ask("An ambiguous question")

    assert result["answer"] is None
    assert result["reason_code"] == "LOW_AGREEMENT"
    assert result["confidence"] == 0.2
    assert answer_calls == []  # never reached the answer stage
    assert len(records) == 1
    assert records[0]["confidence"] == 0.2


def test_ask_abstains_on_ungrounded_answer(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql),
    )
    monkeypatch.setattr(
        execute_module,
        "execute",
        lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)]),
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 999.")
    monkeypatch.setattr(
        verify_module,
        "verify",
        lambda a, c, r: VerifyResult(
            ok=False, ungrounded_numbers=[999.0], detail="unsupported: [999.0]"
        ),
    )

    result = pipeline.ask("q")

    assert result["answer"] is None
    assert result["reason_code"] == "UNGROUNDED_ANSWER"
    assert result["confidence"] == 1.0
    assert result["error"] == "unsupported: [999.0]"
    assert len(records) == 1


def test_ask_returns_full_success_result_with_confidence(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    captured = {}

    def fake_generate(question, schema_context, n=1, temperature=None):
        captured["schema_context"] = schema_context
        return ["SELECT 1"] * n

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql="SELECT 1"),
    )
    monkeypatch.setattr(
        execute_module,
        "execute",
        lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)]),
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 1.")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    result = pipeline.ask("what is 1?")

    assert result["question"] == "what is 1?"
    assert result["sql"] == "SELECT 1"
    assert result["columns"] == ["x"]
    assert result["rows"] == [(1,)]
    assert result["error"] is None
    assert result["answer"] == "The value is 1."
    assert result["reason_code"] is None
    assert result["confidence"] == 1.0
    assert len(records) == 1
    assert records[0]["confidence"] == 1.0
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


def test_ask_threads_db_path_to_guardrails_and_execute(monkeypatch):
    _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    captured = {}

    def fake_validate(sql, db_path=None):
        captured["guardrail_db_path"] = db_path
        return guardrails_module.GuardrailResult(ok=True, sql=sql)

    def fake_execute(sql, db_path=None):
        captured["execute_db_path"] = db_path
        return ExecutionResult(columns=["x"], rows=[(1,)])

    monkeypatch.setattr(guardrails_module, "validate", fake_validate)
    monkeypatch.setattr(execute_module, "execute", fake_execute)
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "answer")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    pipeline.ask("q", db_path="custom.duckdb")

    assert captured["guardrail_db_path"] == "custom.duckdb"
    assert captured["execute_db_path"] == "custom.duckdb"
