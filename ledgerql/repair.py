"""Stage 6b: one repair attempt before abstaining.

Repair feeds a *failure message* back to the generator. That is the whole
mechanism, and it dictates which failures are repairable: only those that
carry a message.

- ``exec_error``: every candidate failed to parse or execute, and none was
  refused for a named reason. The error text is real signal. PHASE_5_5 Task 5.
- ``schema_mismatch``: every candidate referenced a column that does not
  exist. Same task. Built and tested but **disabled** (``ENABLED_TRIGGERS``)
  for the Bridges-2 measurement, which is scoped to ``exec_error`` only: it is
  the path where a correct concept-gap refusal (an invented ``dividend_yield``
  column) could be repaired into a wrong answer, and it has no measurement.

**An empty result is not a repair trigger, and this was tried and cut.**
``empty_entity_bound`` (an entity-bound query returning nothing, aimed at a
wrong exact-match literal such as ``name = 'The Coca-Cola Company'``) was
added on 2026-09-18 and removed on 2026-09-20. A query that returns no rows
succeeded against a valid schema, so there is no error to feed back; the
generator was told "this returned nothing" and could only re-guess. On the
7B it rescued 0 of 15 and handed the motivating case back unchanged. That is
the mechanism, not the model: no model size fixes a feedback loop with no
feedback. See DECISIONS.md, "Rejected design". An empty entity-bound result
goes straight to NO_DATA (result_shape.py).

One attempt, no loops. The repaired SQL goes back through guardrails and
execution and the answer through the verifier exactly like any candidate;
nothing here relaxes a check.

**A stray *table* is never repaired.** guardrails.py reports both a
non-allowlisted table and a non-existent column as SCHEMA_MISMATCH with the
same ``schema_allowlist`` event, but they are opposite situations. A stray
column is the model misremembering the schema, which is repairable. A stray
table (``information_schema.tables``, a staging table) is the request itself
crossing a boundary the guardrail exists to hold -- gold cases S07 and S11
are correct refusals -- and "repairing" it would rewrite a schema-snooping
request into an allowed query and answer it. The check re-derives the
distinction from the AST via guardrails.check_table_allowlist rather than
matching guardrails' detail string.
"""

from __future__ import annotations

from ledgerql import guardrails as guardrails_module
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult

EXEC_ERROR_TRIGGER = "exec_error"
SCHEMA_MISMATCH_TRIGGER = "schema_mismatch"
TRIGGERS = (EXEC_ERROR_TRIGGER, SCHEMA_MISMATCH_TRIGGER)

# What actually fires. Narrower than TRIGGERS on purpose; see the module docstring.
ENABLED_TRIGGERS = frozenset({EXEC_ERROR_TRIGGER})

_FAILURE_TRIGGERS = {
    "EXEC_ERROR": EXEC_ERROR_TRIGGER,
    "SCHEMA_MISMATCH": SCHEMA_MISMATCH_TRIGGER,
}


def _references_disallowed_table(sql: str) -> bool:
    try:
        stmts = guardrails_module.parse_sql(sql)
    except Exception:  # noqa: BLE001 - an unparseable candidate is repairable
        return False
    return any(guardrails_module.check_table_allowlist(stmt) for stmt in stmts if stmt is not None)


def failure_trigger(
    reason_code: str | None,
    guards: list[GuardrailResult],
    enabled: frozenset[str] | tuple[str, ...] | None = None,
) -> str | None:
    """The repair trigger for a no-usable-cluster failure, or None if this
    failure must not be repaired (a deliberate refusal, a stray table, or a
    trigger that is not enabled)."""
    trigger = _FAILURE_TRIGGERS.get(reason_code)
    if trigger is None or trigger not in (ENABLED_TRIGGERS if enabled is None else enabled):
        return None
    if any(_references_disallowed_table(g.sql) for g in guards if not g.ok):
        return None
    return trigger


def failure_feedback(
    guards: list[GuardrailResult], executions: list[ExecutionResult | None]
) -> tuple[str | None, str]:
    """The (sql, error text) to show the model: the first guardrail rejection,
    else the first execution error."""
    for guard in guards:
        if not guard.ok:
            return guard.sql, guard.detail or "rejected"
    for guard, execution in zip(guards, executions, strict=True):
        if execution is not None and execution.error is not None:
            return guard.sql, execution.error
    return None, "no candidate produced a usable result"


def _normalise(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";").strip().lower()


def is_unchanged(original_sql: str | None, repaired_sql: str | None) -> bool:
    """A repair that hands back the same query has repaired nothing."""
    if not original_sql or not repaired_sql:
        return False
    return _normalise(original_sql) == _normalise(repaired_sql)
