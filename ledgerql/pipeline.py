"""Orchestrates the Phase 4 pipeline: classify -> schema -> generate N
candidates -> guardrails validate each -> execute each survivor ->
consensus vote -> answer (question hidden) -> verify -> audit.

Two independent abstain triggers sit between consensus and the answer
stage: no candidate produced a usable result at all (consensus.py sets
reason_code itself), or a usable winner exists but too few of the N
candidates agreed with it (LOW_AGREEMENT_THRESHOLD, checked here). A
third trigger, UNGROUNDED_ANSWER, sits after the answer is written, if
verify.py finds a stated number with nothing backing it in the winning
result.
"""

import time

from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import consensus as consensus_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import schema_index
from ledgerql import verify as verify_module
from ledgerql.execute import ExecutionResult

N_CANDIDATES = 5
LOW_AGREEMENT_THRESHOLD = 0.6


def ask(question: str, db_path: str | None = None) -> dict:
    start = time.monotonic()

    try:
        classify_result = classify_module.classify(question)
        if classify_result.verdict != "IN_SCOPE":
            return _finish(question, start, classify_result, reason_code=classify_result.verdict)

        schema_context = schema_index.get_schema_context()
        sqls = generate_module.generate_candidates(
            question,
            schema_context,
            n=N_CANDIDATES,
            temperature=generate_module.OLLAMA_CONSENSUS_TEMPERATURE,
        )

        guards = []
        for sql in sqls:
            if db_path is not None:
                guards.append(guardrails_module.validate(sql, db_path=db_path))
            else:
                guards.append(guardrails_module.validate(sql))

        execs = []
        for guard in guards:
            if not guard.ok:
                execs.append(None)
                continue
            if db_path is not None:
                execs.append(execute_module.execute(guard.sql, db_path=db_path))
            else:
                execs.append(execute_module.execute(guard.sql))

        consensus_result = consensus_module.vote(guards, execs)

        if consensus_result.reason_code is not None:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                reason_code=consensus_result.reason_code,
                error=consensus_result.detail,
            )

        if consensus_result.agreement < LOW_AGREEMENT_THRESHOLD:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="LOW_AGREEMENT",
                confidence=consensus_result.agreement,
            )

        winner = ExecutionResult(
            columns=consensus_result.columns,
            rows=consensus_result.rows,
            truncated=consensus_result.truncated,
        )
        answer_text = answer_module.write_answer(winner)

        verify_result = verify_module.verify(
            answer_text, consensus_result.columns, consensus_result.rows
        )
        if not verify_result.ok:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="UNGROUNDED_ANSWER",
                error=verify_result.detail,
                confidence=consensus_result.agreement,
            )

        return _finish(
            question,
            start,
            classify_result,
            sql=consensus_result.sql,
            guardrail_events=consensus_result.events,
            columns=consensus_result.columns,
            rows=consensus_result.rows,
            truncated=consensus_result.truncated,
            answer=answer_text,
            confidence=consensus_result.agreement,
        )
    except Exception as e:  # noqa: BLE001
        # Last-resort catch-all: guarantees the master prompt's "every query
        # is logged, nothing silently dropped" constraint holds even when an
        # unhandled exception would otherwise propagate out of ask() before
        # _finish() -- the sole audit.write_record() call site -- is reached.
        fallback_classify = classify_module.ClassifyResult(verdict="EXEC_ERROR", explanation=str(e))
        return _finish(question, start, fallback_classify, reason_code="EXEC_ERROR", error=str(e))


def _finish(
    question: str,
    start: float,
    classify_result,
    sql: str | None = None,
    guardrail_events: list[str] | None = None,
    reason_code: str | None = None,
    columns: list[str] | None = None,
    rows: list[tuple] | None = None,
    truncated: bool = False,
    error: str | None = None,
    answer: str | None = None,
    confidence: float | None = None,
) -> dict:
    guardrail_events = guardrail_events or []
    columns = columns or []
    rows = rows or []
    latency_ms = (time.monotonic() - start) * 1000

    result = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "error": error,
        "answer": answer,
        "reason_code": reason_code,
        "guardrail_events": guardrail_events,
        "confidence": confidence,
    }
    audit_module.write_record(
        {
            "question": question,
            "classify_verdict": classify_result.verdict,
            "classify_explanation": classify_result.explanation,
            "generated_sql": sql,
            "guardrail_events": guardrail_events,
            "execution_summary": {
                "columns": columns,
                "row_count": len(rows),
                "truncated": truncated,
                "error": error,
            },
            "answer": answer,
            "confidence": confidence,
            "reason_code": reason_code,
            "latency_ms": latency_ms,
        }
    )
    return result
