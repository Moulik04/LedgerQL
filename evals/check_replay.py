"""Check a MEASURED run's per-candidate log against the pipeline's own logic.

A report written after per-candidate logging carries a ``candidates`` list per
case (each candidate's guardrail verdict and result shape). That turns three
things that were derived-with-caveats into things that can be *checked*:

1. **6c replays.** consensus.vote() must pick a named rejection reason over the
   generic EXEC_ERROR default. Recomputing it from the logged per-candidate
   reasons must reproduce the recorded reason code, which is what lets the
   "derived figures exclude 6c" caveat be dropped.
2. **Routing replays.** After consensus, the pipeline routes to SCHEMA_MISMATCH
   (a generator that refused in SQL), NO_DATA (entity-bound and empty),
   LOW_AGREEMENT, or an answer. Recomputing that from the log must reproduce the
   recorded reason code.
3. **The derived-replay bounds hold.** evals/replay_derived.py had only the
   winner's agreement, so it reported an upper bound (every winner-empty
   entity-bound record flips) and a lower bound (agreement 1.0 only). With
   survivors logged the exact answer exists, and it must sit between them.

Usage: ``python -m evals.check_replay reports/<measured>.jsonl``; exits non-zero
if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ledgerql import consensus
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult
from ledgerql.pipeline import LOW_AGREEMENT_THRESHOLD
from ledgerql.result_shape import (
    is_entity_bound,
    is_identity_anchored_empty,
    is_tautologically_empty,
)

_CONSENSUS_FAILURE_CODES = {"EXEC_ERROR", "SCHEMA_MISMATCH", "OUT_OF_SCOPE", "COST_LIMIT"}


def load_report(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _survivors(record: dict) -> list[dict]:
    return [c for c in record.get("candidates") or [] if c["n_rows"] is not None]


def _winner_rows(record: dict) -> list[tuple]:
    return [tuple(r) for r in record.get("rows") or []]


def exact_no_data_signal(record: dict) -> bool | None:
    """The pipeline's NO_DATA condition, recomputed exactly from the candidate
    log (``pipeline._no_data_signal``). None if there is nothing to compute from:
    no candidate log, or no candidate executed."""
    survivors = _survivors(record)
    if not survivors:
        return None
    sql = record.get("generated_sql")
    if all(c["empty"] for c in survivors) and is_entity_bound(sql):
        return True
    agreement = record.get("confidence")
    return (
        agreement is not None
        and agreement >= LOW_AGREEMENT_THRESHOLD
        and is_identity_anchored_empty(sql, _winner_rows(record))
    )


def check_bounds(records: list[dict]) -> dict:
    """Does lower <= exact <= upper hold, and how loose were the bounds?"""
    violations, upper_minus_exact, exact_minus_lower, n = [], [], [], 0
    for r in records:
        exact = exact_no_data_signal(r)
        if exact is None:
            continue
        n += 1
        upper = is_identity_anchored_empty(r.get("generated_sql"), _winner_rows(r))
        lower = upper and r.get("confidence") == 1.0
        if lower and not exact:
            violations.append((r["id"], "lower bound flips a record the exact rule does not"))
        if exact and not upper:
            violations.append((r["id"], "exact rule flips a record the upper bound missed"))
        if upper and not exact:
            upper_minus_exact.append(r["id"])
        if exact and not lower:
            exact_minus_lower.append(r["id"])
    return {
        "n_checked": n,
        "violations": violations,
        "upper_minus_exact": upper_minus_exact,
        "exact_minus_lower": exact_minus_lower,
    }


def _predicted_route(record: dict) -> str:
    survivors = _survivors(record)
    sql = record.get("generated_sql")
    if is_tautologically_empty(sql) and all(c["empty"] for c in survivors):
        return "SCHEMA_MISMATCH"
    if exact_no_data_signal(record):
        return "NO_DATA"
    if record["confidence"] < LOW_AGREEMENT_THRESHOLD:
        return "LOW_AGREEMENT"
    return "ANSWER"


def replay_routing(records: list[dict]) -> dict:
    """Recompute the post-consensus routing from the log and compare it with the
    recorded reason code. Repaired records are skipped (a repaired result has no
    agreement), as are cases where no candidate executed (consensus failures)."""
    checked, mismatches = 0, []
    for r in records:
        if r.get("repair") or r.get("confidence") is None or not _survivors(r):
            continue
        checked += 1
        predicted, recorded = _predicted_route(r), r["reason_code"]
        ok = (
            recorded in (None, "UNGROUNDED_ANSWER")
            if predicted == "ANSWER"
            else recorded == predicted
        )
        if not ok:
            mismatches.append((r["id"], recorded, predicted))
    return {"checked": checked, "mismatches": mismatches}


def replay_consensus_reasons(records: list[dict]) -> dict:
    """6c: recompute consensus.vote()'s reason code for cases where no candidate
    executed, from the logged per-candidate guardrail reasons."""
    checked, mismatches = 0, []
    for r in records:
        cands = r.get("candidates")
        if not cands or _survivors(r) or r.get("reason_code") not in _CONSENSUS_FAILURE_CODES:
            continue
        guards = [
            GuardrailResult(
                ok=c["guard_ok"],
                sql=c["sql"],
                events=list(c["events"]),
                reason_code=c["reason_code"],
                detail=c["detail"],
            )
            for c in cands
        ]
        execs = [
            ExecutionResult(error=c["exec_error"]) if c["guard_ok"] and c["exec_error"] else None
            for c in cands
        ]
        replayed = consensus.vote(guards, execs).reason_code
        checked += 1
        if replayed != r["reason_code"]:
            mismatches.append((r["id"], r["reason_code"], replayed))
    return {"checked": checked, "mismatches": mismatches}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    args = ap.parse_args(argv)
    records = load_report(args.report)
    with_log = sum(1 for r in records if r.get("candidates"))
    print(f"{args.report}: {len(records)} records, {with_log} with a per-candidate log")
    if not with_log:
        print("FAIL: no per-candidate log; this is not a measured post-logging report")
        return 1

    routing = replay_routing(records)
    six_c = replay_consensus_reasons(records)
    bounds = check_bounds(records)
    print(
        f"routing replays:   {routing['checked'] - len(routing['mismatches'])}/{routing['checked']}"
        f"  mismatches: {routing['mismatches']}"
    )
    print(
        f"6c replays:        {six_c['checked'] - len(six_c['mismatches'])}/{six_c['checked']}"
        f"  mismatches: {six_c['mismatches']}"
    )
    print(f"replay bounds:     {bounds['n_checked']} checked, violations: {bounds['violations']}")
    print(f"  upper bound was loose on: {bounds['upper_minus_exact']}")
    print(f"  lower bound was loose on: {bounds['exact_minus_lower']}")
    failed = routing["mismatches"] or six_c["mismatches"] or bounds["violations"]
    print("FAIL" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
