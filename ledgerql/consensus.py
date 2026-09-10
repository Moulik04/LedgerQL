"""Stage 6: self-consistency vote.

Clusters executed candidates by result set (not raw SQL text -- two
differently-worded but semantically-equivalent queries should agree).
The majority cluster wins; agreement is scored against the full
requested sample count, not just the candidates that executed
successfully, so a low SQL-generation success rate is itself a
low-confidence signal instead of being hidden by only comparing
survivors to each other.
"""

from collections import Counter
from dataclasses import dataclass, field

from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


@dataclass
class ConsensusResult:
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    agreement: float = 0.0
    events: list[str] = field(default_factory=list)
    reason_code: str | None = None
    detail: str | None = None


def _row_sort_key(row: tuple) -> tuple:
    # None-safe: comparing None to a non-None value raises TypeError in
    # Python 3, and real result rows can contain None (nullable columns
    # like fiscal_period). Pairing each value with an is-None flag makes
    # every row comparable without ever comparing None to a non-None value.
    return tuple((v is None, v) for v in row)


def vote(
    guards: list[GuardrailResult], executions: list[ExecutionResult | None]
) -> ConsensusResult:
    n = len(guards)
    clusters: dict[tuple, list[int]] = {}
    for i, exec_result in enumerate(executions):
        if exec_result is None or exec_result.error is not None:
            continue
        key = (tuple(exec_result.columns), tuple(sorted(exec_result.rows, key=_row_sort_key)))
        clusters.setdefault(key, []).append(i)

    all_events: list[str] = []
    for guard in guards:
        all_events.extend(guard.events)
    deduped_events = sorted(set(all_events))

    if not clusters:
        rejection_reasons = [g.reason_code for g in guards if g.reason_code is not None]
        if rejection_reasons:
            reason_code = Counter(rejection_reasons).most_common(1)[0][0]
        else:
            reason_code = "EXEC_ERROR"
        first_rejected_sql = next((g.sql for g in guards if not g.ok), None)
        return ConsensusResult(
            sql=first_rejected_sql,
            agreement=0.0,
            events=deduped_events,
            reason_code=reason_code,
            detail="no candidate produced a usable result",
        )

    winning_key, winning_indices = max(clusters.items(), key=lambda kv: len(kv[1]))
    winner_idx = winning_indices[0]
    winner_exec = executions[winner_idx]
    winner_guard = guards[winner_idx]

    return ConsensusResult(
        sql=winner_guard.sql,
        columns=winner_exec.columns,
        rows=winner_exec.rows,
        truncated=winner_exec.truncated,
        agreement=len(winning_indices) / n,
        events=deduped_events,
        reason_code=None,
        detail=None,
    )
