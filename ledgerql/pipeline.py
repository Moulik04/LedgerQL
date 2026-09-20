"""Orchestrates the Phase 4 pipeline: intent -> classify -> schema ->
generate N candidates -> guardrails validate each -> execute each
survivor -> consensus vote -> answer (question hidden) -> verify ->
audit.

Stage 0 (intent) is a deterministic, regex-based check on the raw
question text, ahead of the LLM classifier. It owns the one category
neither other layer can: a request whose malicious clause the generator
silently discards, so that guardrails.py -- which only ever sees
generated SQL -- has nothing left to reject. See ledgerql/intent.py.

Three independent abstain triggers sit between consensus and the answer
stage: no candidate produced a usable result at all (consensus.py sets
reason_code itself); every candidate that executed came back empty (or a
single row of NULL) on a query bound to one specific company (result_shape.py,
NO_DATA -- see docs/superpowers/specs/2026-09-16-phase5.5-task6b-design.md
section 1), checked first because agreement's denominator is N, not the
survivors; or a usable winner exists but too few of the N candidates agreed
with it (LOW_AGREEMENT_THRESHOLD, checked here). A
fourth trigger, UNGROUNDED_ANSWER, sits after the answer is written, if
verify.py finds a stated number with nothing backing it in the winning
result.

Before a no-usable-result abstain commits, one repair attempt is made when the
failure carries an error message (repair.py, exec_error only for now, never a
loop); its output goes back through guardrails, execution and the verifier. An
empty result is never repaired (no message to feed back): it is NO_DATA. A generator that refuses
in SQL (`SELECT NULL ... WHERE 1 = 0`) is mapped to SCHEMA_MISMATCH
structurally and is not repaired.
"""

import functools
import time

from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import consensus as consensus_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import intent as intent_module
from ledgerql import repair as repair_module
from ledgerql import result_shape as result_shape_module
from ledgerql import schema_index
from ledgerql import verify as verify_module
from ledgerql.execute import ExecutionResult

N_CANDIDATES = 5
LOW_AGREEMENT_THRESHOLD = 0.6


def ask(question: str, db_path: str | None = None) -> dict:
    start = time.monotonic()

    try:
        # Stage 0, before classify: a deterministic check on the question
        # text. It runs first precisely because it must not depend on an
        # LLM call -- classify.py is a sampled judgment and varies by
        # model, which is how S02 came to be refused for three different
        # reasons on three different models. See ledgerql/intent.py.
        intent_result = intent_module.check(question)
        if not intent_result.ok:
            return _finish(
                question,
                start,
                classify_module.ClassifyResult(
                    verdict=intent_result.reason_code, explanation=intent_result.detail or ""
                ),
                guardrail_events=intent_result.events,
                reason_code=intent_result.reason_code,
                error=intent_result.detail,
            )

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

        # One entry per generated candidate, so a run can be replayed exactly:
        # each candidate's guardrail reason and what it returned.
        candidates_log = _candidate_log(sqls, guards, execs)
        finish = functools.partial(_finish, candidates=candidates_log)
        answer_from = functools.partial(_answer_from, candidates=candidates_log)

        # Evaluated over the candidates that actually executed, and BEFORE the
        # agreement gate: agreement divides by N, so one survivor among four
        # errored candidates reads as 0.2 and hides that everything that ran
        # was unanimously empty. Unanimity among survivors is the signal.
        survivor_rows = [e.rows for e in execs if e is not None and e.error is None]

        # A generator that answers in SQL that it cannot express the question
        # (`SELECT NULL AS credit_rating WHERE 1 = 0`) has told us the concept
        # is not in this schema. Decided structurally, and not repaired: a
        # repair would push it to invent the thing it just declined to invent.
        if (
            consensus_result.reason_code is None
            and result_shape_module.is_tautologically_empty(consensus_result.sql)
            and result_shape_module.survivors_unanimously_empty(survivor_rows)
        ):
            return finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="SCHEMA_MISMATCH",
                confidence=consensus_result.agreement,
            )

        # An empty entity-bound result is NO_DATA, never a repair: the query
        # succeeded against a valid schema, so there is no error to feed back.
        # (Tried as a repair trigger and cut; see repair.py and DECISIONS.md.)
        if consensus_result.reason_code is None and _no_data_signal(
            consensus_result, survivor_rows
        ):
            return finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="NO_DATA",
                confidence=consensus_result.agreement,
            )

        if consensus_result.reason_code is not None:
            trigger = repair_module.failure_trigger(consensus_result.reason_code, guards)
            if trigger is None:
                return finish(
                    question,
                    start,
                    classify_result,
                    sql=consensus_result.sql,
                    guardrail_events=consensus_result.events,
                    reason_code=consensus_result.reason_code,
                    error=consensus_result.detail,
                )
            failing_sql, error_text = repair_module.failure_feedback(guards, execs)
            # One repair attempt, never a loop. What it produces goes back
            # through guardrails, execution and the verifier like any candidate.
            repair, repaired = _attempt_repair(
                question, schema_context, trigger, failing_sql, error_text, db_path
            )
            if repaired is None:
                # Repair produced nothing usable: abstain exactly as before.
                return finish(
                    question,
                    start,
                    classify_result,
                    sql=consensus_result.sql,
                    guardrail_events=consensus_result.events,
                    reason_code=consensus_result.reason_code,
                    error=consensus_result.detail,
                    repair=repair,
                )
            guard, execution = repaired
            if result_shape_module.is_entity_bound_no_data(guard.sql, [execution.rows]):
                return finish(
                    question,
                    start,
                    classify_result,
                    sql=guard.sql,
                    guardrail_events=consensus_result.events,
                    columns=execution.columns,
                    rows=execution.rows,
                    truncated=execution.truncated,
                    reason_code="NO_DATA",
                    repair=repair,
                )
            # No self-consistency signal exists for a single repaired
            # candidate, so no agreement is claimed: confidence stays None.
            return answer_from(
                question,
                start,
                classify_result,
                sql=guard.sql,
                events=consensus_result.events,
                columns=execution.columns,
                rows=execution.rows,
                truncated=execution.truncated,
                confidence=None,
                repair=repair,
            )

        if consensus_result.agreement < LOW_AGREEMENT_THRESHOLD:
            return finish(
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

        return answer_from(
            question,
            start,
            classify_result,
            sql=consensus_result.sql,
            events=consensus_result.events,
            columns=consensus_result.columns,
            rows=consensus_result.rows,
            truncated=consensus_result.truncated,
            confidence=consensus_result.agreement,
        )
    except Exception as e:  # noqa: BLE001
        # Last-resort catch-all: guarantees the master prompt's "every query
        # is logged, nothing silently dropped" constraint holds even when an
        # unhandled exception would otherwise propagate out of ask() before
        # _finish() -- the sole audit.write_record() call site -- is reached.
        fallback_classify = classify_module.ClassifyResult(verdict="EXEC_ERROR", explanation=str(e))
        return _finish(question, start, fallback_classify, reason_code="EXEC_ERROR", error=str(e))


def _no_data_signal(consensus_result, survivor_rows: list[list[tuple]]) -> bool:
    """Two ways to establish an empty, entity-bound result, and neither
    subsumes the other:

    - every candidate that executed came back empty (survivor unanimity),
      which the agreement gate can mask because agreement divides by N; or
    - the winning cluster is empty and clears the agreement gate, even though a
      survivor dissents. Unanimity alone misses this: on the 7B, M07 and M04
      sat at agreement 0.8 with one dissenting survivor, failed the unanimity
      test, and were answered from an empty table -- the original defect,
      reintroduced by making the predicate stricter.

    Below the gate with a dissent, the honest reason is LOW_AGREEMENT.
    """
    if result_shape_module.is_entity_bound_no_data(consensus_result.sql, survivor_rows):
        return True
    return consensus_result.agreement >= LOW_AGREEMENT_THRESHOLD and (
        result_shape_module.is_identity_anchored_empty(consensus_result.sql, consensus_result.rows)
    )


def _candidate_log(
    sqls: list[str],
    guards: list,
    execs: list,
) -> list[dict]:
    """A JSON-safe record per generated candidate: its guardrail verdict (reason
    code, events, detail) and, if it executed, its row count and whether that
    result was empty/all-NULL. Recorded so a run can be replayed exactly."""
    log = []
    for sql, guard, execution in zip(sqls, guards, execs, strict=True):
        ran = execution is not None and execution.error is None
        log.append(
            {
                "sql": sql,
                "guard_ok": guard.ok,
                "reason_code": guard.reason_code,
                "events": list(guard.events),
                "detail": guard.detail,
                "exec_error": execution.error if execution is not None else None,
                "n_rows": len(execution.rows) if ran else None,
                "empty": result_shape_module.is_empty_or_null(execution.rows) if ran else None,
            }
        )
    return log


def _attempt_repair(
    question: str,
    schema_context: str,
    trigger: str,
    failing_sql: str | None,
    error_text: str,
    db_path: str | None,
):
    """One repair attempt. Returns (repair_record, (guard, execution) | None);
    the second element is None whenever the repair produced nothing usable --
    the model handed back the same query, guardrails rejected it, or it failed
    to execute."""
    repair: dict = {"trigger": trigger, "sql": None}
    try:
        repaired_sql = generate_module.repair_candidate(
            question, schema_context, failing_sql or "", error_text
        )
    except Exception as e:  # noqa: BLE001 - a repair hiccup must not lose the original reason
        repair["error"] = str(e)
        return repair, None
    repair["sql"] = repaired_sql
    if not repaired_sql or repair_module.is_unchanged(failing_sql, repaired_sql):
        return repair, None

    if db_path is not None:
        guard = guardrails_module.validate(repaired_sql, db_path=db_path)
    else:
        guard = guardrails_module.validate(repaired_sql)
    if not guard.ok:
        return repair, None
    if db_path is not None:
        execution = execute_module.execute(guard.sql, db_path=db_path)
    else:
        execution = execute_module.execute(guard.sql)
    if execution.error is not None:
        return repair, None
    repair["sql"] = guard.sql
    return repair, (guard, execution)


def _answer_from(
    question: str,
    start: float,
    classify_result,
    *,
    sql: str | None,
    events: list[str],
    columns: list[str],
    rows: list[tuple],
    truncated: bool,
    confidence: float | None,
    repair: dict | None = None,
    candidates: list[dict] | None = None,
) -> dict:
    """Write the answer from a winning result, verify it, and finish. Shared by
    the consensus path and the repaired path so both are gated identically."""
    winner = ExecutionResult(columns=columns, rows=rows, truncated=truncated)
    answer_text = answer_module.write_answer(winner)

    verify_result = verify_module.verify(answer_text, columns, rows)
    if not verify_result.ok:
        return _finish(
            question,
            start,
            classify_result,
            sql=sql,
            guardrail_events=events,
            columns=columns,
            rows=rows,
            truncated=truncated,
            reason_code="UNGROUNDED_ANSWER",
            error=verify_result.detail,
            confidence=confidence,
            repair=repair,
            candidates=candidates,
        )

    return _finish(
        question,
        start,
        classify_result,
        sql=sql,
        guardrail_events=events,
        columns=columns,
        rows=rows,
        truncated=truncated,
        answer=answer_text,
        confidence=confidence,
        repair=repair,
        candidates=candidates,
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
    confidence: float | None = None,
    repair: dict | None = None,
    candidates: list[dict] | None = None,
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
        "repair": repair,
    }
    if candidates is not None:
        result["candidates"] = candidates
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
            "repair": repair,
            "candidates": candidates,
            "latency_ms": latency_ms,
        }
    )
    return result
