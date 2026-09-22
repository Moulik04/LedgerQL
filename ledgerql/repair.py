"""Stage 6b: one repair attempt before abstaining.

Repair feeds a *failure message* back to the generator. That is the whole
mechanism, and it dictates which failures are repairable: only those that
carry a message.

- ``exec_error``: every candidate failed to parse or execute, and none was
  refused for a named reason. The error text is real signal. PHASE_5_5 Task 5.
  Measured on Bridges-2 (2026-09-20) and **cut 2026-09-21**: see below.
- ``schema_mismatch``: every candidate referenced a column that does not
  exist. Same task. Built and tested but **disabled** (``ENABLED_TRIGGERS``)
  for the Bridges-2 measurement, which was scoped to ``exec_error`` only: it is
  the path where a correct concept-gap refusal (an invented ``dividend_yield``
  column) could be repaired into a wrong answer, and it had no measurement.

**``exec_error``, cut 2026-09-21: converting a correct refusal into a wrong
answer is strictly worse than an unrescued abstain, and it did that more often
than it helped.** This is the same principle ``schema_mismatch`` was scoped
out under, applied to a trigger that was actually measured rather than merely
suspected. On the 30B Bridges-2 run: 7 attempts, 5 rescues (a rescue = the
repair turned an abstain into an answer, ``evals/repair_scoring.py``), of
which only 1 was correct and 3 converted a required abstain into a wrong
answer -- at most 2 helpful against 3 harmful, net negative under any
weighting that doesn't discount the harm column to zero. See DECISIONS.md,
"exec_error cut, criterion corrected" for the criterion that was originally
used (which missed this because it counted a rescue as a win regardless of
correctness), the full counts on both models, and the counterfactual replay.
Both triggers are disabled by default now; re-enabling either for a future
measurement is one line (``ENABLED_TRIGGERS``), same as before.

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

# What actually fires. Empty: both triggers are measured-or-suspected harmful
# (see the module docstring) and disabled. Re-enabling either is one line.
ENABLED_TRIGGERS: frozenset[str] = frozenset()

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
