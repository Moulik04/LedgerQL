"""Task 7: pass@1 vs pass@N, replayed locally from already-logged candidate
SQL -- no GPU, no new pipeline run.

pass@1 is accuracy as already scored (`execution_correct` on the consensus
winner). pass@N asks a different question: across the N sampled candidates,
did ANY of them produce gold's result? A large gap means a correct query was
generated and then discarded by `consensus.vote()` -- selection is the
lever, and no amount of model capacity or fine-tuning fixes that. A small
gap means generation itself is the ceiling.

Reproduces each candidate's guard+execute stage exactly and deterministically
from its logged raw `sql` (`ledgerql.guardrails.validate` is a pure function
of SQL text plus read-only DB state, so re-running it on the same text
reproduces the same `GuardrailResult` the live pipeline got, including any
rewrite -- `guard.sql`, not the logged pre-rewrite `sql`, is what actually
gets executed, exactly mirroring `ledgerql/pipeline.py`'s own guard-then-
execute loop). A candidate whose guardrail rejected it (`ok=False`) was
never executed by the live pipeline either (see `pipeline.py`'s
`execs.append(None)` branch) -- it has no result to compare, so it is
correctly scored as a non-match rather than specially excluded.

Scored only over `ANSWER`-expected cases, the same population
`overall_execution_accuracy` is already computed over in `run_eval.py` --
pass@1 here is a byproduct consistency check against that existing figure,
not a new definition of it.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import duckdb

from evals.run_eval import results_match
from ledgerql import execute as execute_module
from ledgerql import guardrails as guardrails_module

GOLD_PATH = Path(__file__).resolve().parent / "gold.jsonl"

_SCORED_EXPECTED = "ANSWER"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _candidate_matches_gold(
    sql: str, gold_rows: list[tuple], compare: str, tolerance: float, db_path: str
) -> bool:
    guard = guardrails_module.validate(sql, db_path=db_path)
    if not guard.ok:
        return False
    execution = execute_module.execute(guard.sql, db_path=db_path)
    if execution.error is not None:
        return False
    return results_match(gold_rows, execution.rows, compare, tolerance)


def _empty_bucket() -> dict:
    return {"total": 0, "pass_1": 0, "pass_n": 0}


def compute_pass_at_n(per_case: list[dict], cases_by_id: dict, db_path: str) -> dict:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        by_tier: dict[str, dict[str, int]] = defaultdict(_empty_bucket)
        overall = _empty_bucket()

        for record in per_case:
            case = cases_by_id.get(record["id"])
            if case is None or case["expected"] != _SCORED_EXPECTED:
                continue
            tier = case["tier"]
            by_tier[tier]["total"] += 1
            overall["total"] += 1

            if record.get("execution_correct") is True:
                by_tier[tier]["pass_1"] += 1
                overall["pass_1"] += 1

            gold_rows = con.execute(case["gold_sql"]).fetchall()
            tolerance = case.get("tolerance", 1e-6)
            any_match = any(
                _candidate_matches_gold(cand["sql"], gold_rows, case["compare"], tolerance, db_path)
                for cand in (record.get("candidates") or [])
            )
            if any_match:
                by_tier[tier]["pass_n"] += 1
                overall["pass_n"] += 1
    finally:
        con.close()

    def _rates(bucket: dict) -> dict:
        total = bucket["total"]
        pass_1 = bucket["pass_1"] / total if total else 0.0
        pass_n = bucket["pass_n"] / total if total else 0.0
        return {"total": total, "pass_at_1": pass_1, "pass_at_n": pass_n, "gap": pass_n - pass_1}

    return {
        "overall": _rates(overall),
        "by_tier": {tier: _rates(bucket) for tier, bucket in sorted(by_tier.items())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    args = ap.parse_args(argv)

    cases_by_id = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    per_case = load_jsonl(args.report)
    stats = compute_pass_at_n(per_case, cases_by_id, args.db)

    o = stats["overall"]
    print(f"{args.report}: {o['total']} ANSWER-expected cases")
    print(f"  pass@1: {o['pass_at_1']:.1%}   pass@N: {o['pass_at_n']:.1%}   gap: {o['gap']:.1%}")
    print()
    print(f"{'tier':<15} {'n':>4} {'pass@1':>8} {'pass@N':>8} {'gap':>8}")
    for tier, r in stats["by_tier"].items():
        p1, pn, gap = r["pass_at_1"], r["pass_at_n"], r["gap"]
        print(f"{tier:<15} {r['total']:>4} {p1:>7.1%} {pn:>7.1%} {gap:>7.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
