"""Offline candidate execution for scoring: the outcome must not depend on machine load.

The live pipeline runs a candidate under a 10 s timeout, and there a slow query is legitimately an
`EXEC_ERROR` (`ledgerql/execute.py`). Re-scoring recorded candidates is a different job: the
question is whether the SQL is *right*, so a verdict must never turn on how busy the machine is.
Here a candidate runs under a timeout far above any observed query time (the slowest of the 1,000
A/B candidates took 0.04 s on an idle machine), and every outcome gets its own status instead of
collapsing into "wrong":

- `ok`: ran; rows and columns recorded.
- `guard_rejected`: the guardrails refuse it (deterministic).
- `error`: it raised, and raised the same way on every attempt (a real SQL error).
- `timeout`: it hit the timeout on every attempt.
- `unstable`: it failed on every attempt but not the same way each time: the failure was the
  environment, not the SQL.

Anything that is not `ok` is retried, up to `ATTEMPTS` runs, so a transient failure cannot
survive as a verdict: a candidate that fails and then runs is `ok` (with `attempts` above 1).
`timeout` and `unstable` that remain are scoring failures: a decision run raises
`ScoringIncomplete` and lists them (`require_resolved`), it does not score them as wrong.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ledgerql import execute as execute_module
from ledgerql import guardrails as guardrails_module

OFFLINE_TIMEOUT_SECONDS = float(os.environ.get("LEDGERQL_OFFLINE_TIMEOUT_SECONDS", "120"))
ATTEMPTS = 3
# `ledgerql.execute.execute` reports a timeout only as this error text.
_TIMEOUT_PREFIX = "query timed out after"
UNRESOLVED = ("timeout", "unstable")


class ScoringIncomplete(RuntimeError):
    """A candidate could not be scored reliably; a verdict would depend on the environment."""


@dataclass
class Outcome:
    status: str
    guard_sql: str | None = None
    rows: list | None = None
    columns: list[str] | None = None
    error: str | None = None
    attempts: int = 1


def _attempt(sql: str, db_path: str, timeout: float) -> Outcome:
    guard = guardrails_module.validate(sql, db_path=db_path)
    if not guard.ok:
        return Outcome("guard_rejected")
    execution = execute_module.execute(guard.sql, db_path=db_path, timeout_seconds=timeout)
    if execution.error is None:
        return Outcome("ok", guard.sql, execution.rows, execution.columns)
    status = "timeout" if execution.error.startswith(_TIMEOUT_PREFIX) else "error"
    return Outcome(status, error=execution.error)


def run_candidate(
    sql: str,
    db_path: str,
    timeout: float | None = None,
    attempts: int = ATTEMPTS,
    runner=_attempt,
) -> Outcome:
    timeout = OFFLINE_TIMEOUT_SECONDS if timeout is None else timeout
    seen: list[Outcome] = []
    for _ in range(attempts):
        out = runner(sql, db_path, timeout)
        seen.append(out)
        if out.status in ("ok", "guard_rejected"):
            break
    last = seen[-1]
    last.attempts = len(seen)
    if last.status in ("error", "timeout") and len({(o.status, o.error) for o in seen}) > 1:
        last.status = "unstable"
        last.error = "; ".join(sorted({o.error or o.status for o in seen}))
    return last


def require_resolved(outcomes: dict[str, Outcome]) -> None:
    """Fail loudly if any outcome (keyed by a label) is a timeout or unstable."""
    bad = {k: o for k, o in outcomes.items() if o.status in UNRESOLVED}
    if bad:
        lines = [
            f"  {k}: {o.status} after {o.attempts} attempts: {o.error}" for k, o in bad.items()
        ]
        raise ScoringIncomplete(
            f"{len(bad)} candidate(s) could not be scored reliably (timeout or unstable); the "
            "run is not valid and none of them is scored as wrong:\n" + "\n".join(lines)
        )
