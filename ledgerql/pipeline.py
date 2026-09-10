"""Orchestrates the Phase 3 guarded pipeline: classify -> schema ->
generate -> guardrails -> execute -> answer -> audit.

classify.py (Layer 1) is a soft prefilter that can short-circuit
before generation ever runs. guardrails.py (Layer 4) is the hard
backstop that validates whatever SQL actually gets generated,
independent of what classify.py decided. audit.py (Layer 8) writes
exactly one record on every exit path via the shared _finish() helper
below, satisfying the master prompt's 'every query is logged' hard
constraint even on the classify/guardrail-rejected paths.
"""

import time

from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import schema_index


def ask(question: str, db_path: str | None = None) -> dict:
    start = time.monotonic()

    classify_result = classify_module.classify(question)
    if classify_result.verdict != "IN_SCOPE":
        return _finish(question, start, classify_result, reason_code=classify_result.verdict)

    schema_context = schema_index.get_schema_context()
    sql = generate_module.generate_candidates(question, schema_context, n=1)[0]

    if db_path is not None:
        guard = guardrails_module.validate(sql, db_path=db_path)
    else:
        guard = guardrails_module.validate(sql)

    if not guard.ok:
        return _finish(
            question,
            start,
            classify_result,
            sql=sql,
            guardrail_events=guard.events,
            reason_code=guard.reason_code,
            error=guard.detail,
        )

    if db_path is not None:
        exec_result = execute_module.execute(guard.sql, db_path=db_path)
    else:
        exec_result = execute_module.execute(guard.sql)

    if exec_result.error is not None:
        return _finish(
            question,
            start,
            classify_result,
            sql=guard.sql,
            guardrail_events=guard.events,
            reason_code="EXEC_ERROR",
            columns=exec_result.columns,
            rows=exec_result.rows,
            truncated=exec_result.truncated,
            error=exec_result.error,
        )

    answer_text = answer_module.write_answer(question, exec_result)
    return _finish(
        question,
        start,
        classify_result,
        sql=guard.sql,
        guardrail_events=guard.events,
        columns=exec_result.columns,
        rows=exec_result.rows,
        truncated=exec_result.truncated,
        answer=answer_text,
    )


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
            "confidence": None,
            "reason_code": reason_code,
            "latency_ms": latency_ms,
        }
    )
    return result
