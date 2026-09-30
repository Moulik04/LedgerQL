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

from evals.scoring import case_matches, load_gold
from ledgerql import execute as execute_module
from ledgerql import guardrails as guardrails_module

GOLD_PATH = Path(__file__).resolve().parent / "gold.jsonl"

_SCORED_EXPECTED = "ANSWER"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class PassNInvariantError(AssertionError):
    """pass@1 and pass@N were computed inconsistently for one case."""


def assert_winner_implies_candidate(
    case_id: str, *, winner_correct: bool, any_candidate_correct: bool
) -> None:
    """The winner is one of the N candidates, so a correct winner means some
    candidate is correct; pass@N >= pass@1 per case, hence per tier."""
    if winner_correct and not any_candidate_correct:
        raise PassNInvariantError(
            f"{case_id}: winner is correct but no candidate is -- pass@1 and "
            "pass@N are not being computed from the same executions"
        )


def _run_candidate_ex(
    sql: str, db_path: str
) -> tuple[str | None, list[tuple] | None, list[str] | None]:
    """The live pipeline's guard-then-execute stage: (guard.sql, rows, column names), or
    (None, None, None) if guardrails rejected it or it errored."""
    guard = guardrails_module.validate(sql, db_path=db_path)
    if not guard.ok:
        return None, None, None
    execution = execute_module.execute(guard.sql, db_path=db_path)
    if execution.error is not None:
        return None, None, None
    return guard.sql, execution.rows, execution.columns


def _run_candidate(sql: str, db_path: str) -> tuple[str | None, list[tuple] | None]:
    """(guard.sql, rows), or (None, None) if guardrails rejected it or it errored."""
    guard_sql, rows, _ = _run_candidate_ex(sql, db_path)
    return guard_sql, rows


def _canonical_rows(rows: list) -> list[str]:
    # Reports are written with json.dumps(default=str); compare in that form,
    # order-insensitively (an unordered SELECT DISTINCT is not stable run to run).
    return sorted(json.dumps(row, default=str) for row in rows)


def _new_bucket() -> dict:
    return {"total": 0, "pass_1": 0, "pass_n": 0, "winner_outside_pool_correct": 0}


def compute_pass_at_n(per_case: list[dict], cases_by_id: dict, db_path: str) -> dict:
    # read_only=True: a wrong path raises instead of creating an empty DB.
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        by_tier: dict[str, dict[str, int]] = defaultdict(_new_bucket)
        overall = _new_bucket()
        drift: list[dict] = []
        rows_drift: list[str] = []

        for record in per_case:
            case = cases_by_id.get(record["id"])
            if case is None or case["expected"] != _SCORED_EXPECTED:
                continue
            gold_rows = con.execute(case["gold_sql"]).fetchall()

            pool: list[tuple[str, bool, list[tuple]]] = []
            for cand in record.get("candidates") or []:
                guard_sql, rows, columns = _run_candidate_ex(cand["sql"], db_path)
                if guard_sql is not None:
                    matched = case_matches(case, gold_rows, rows, db_path, pred_columns=columns)
                    pool.append((guard_sql, matched, rows))
            any_correct = any(matched for _, matched, _ in pool)

            # pass@1 is the vote's pick, re-executed locally with the same
            # comparator as pass@N. A winner not among the candidates (an
            # exec_error repair) is outside the N and cannot be pass@1 of it.
            winner_sql = record.get("generated_sql")
            in_pool = [(m, r) for gs, m, r in pool if gs == winner_sql]
            winner_correct = bool(in_pool) and in_pool[0][0]
            assert_winner_implies_candidate(
                record["id"], winner_correct=winner_correct, any_candidate_correct=any_correct
            )

            outside_correct = False
            if not in_pool and winner_sql:
                _, rows, columns = _run_candidate_ex(winner_sql, db_path)
                outside_correct = rows is not None and case_matches(
                    case, gold_rows, rows, db_path, pred_columns=columns
                )

            recorded = record.get("execution_correct") is True
            if recorded != winner_correct:
                if not in_pool and record.get("repair"):
                    cause = "repair_rescue"
                elif winner_correct and record.get("answer") is None:
                    cause = "post_vote_gate"
                else:
                    cause = "unexplained"
                drift.append(
                    {"id": record["id"], "tier": case["tier"], "recorded": recorded,
                     "local": winner_correct, "cause": cause}
                )  # fmt: skip

            if in_pool and record.get("reason_code") is None and record.get("rows") is not None:
                if _canonical_rows(in_pool[0][1]) != _canonical_rows(record["rows"]):
                    rows_drift.append(record["id"])

            for bucket in (by_tier[case["tier"]], overall):
                bucket["total"] += 1
                bucket["pass_1"] += winner_correct
                bucket["pass_n"] += any_correct
                bucket["winner_outside_pool_correct"] += outside_correct
    finally:
        con.close()

    def _rates(bucket: dict) -> dict:
        total = bucket["total"]
        return {
            **bucket,
            "pass_at_1": bucket["pass_1"] / total if total else 0.0,
            "pass_at_n": bucket["pass_n"] / total if total else 0.0,
            "gap": (bucket["pass_n"] - bucket["pass_1"]) / total if total else 0.0,
        }

    return {
        "overall": _rates(overall),
        "by_tier": {tier: _rates(bucket) for tier, bucket in sorted(by_tier.items())},
        "drift": drift,
        "rows_drift": rows_drift,
    }


def _line(label: str, b: dict) -> str:
    n = b["total"]
    p1, pn = f"{b['pass_1']}/{n} {b['pass_at_1']:.0%}", f"{b['pass_n']}/{n} {b['pass_at_n']:.0%}"
    return f"{label:<17} {n:>3} {p1:>13} {pn:>13} {b['pass_n'] - b['pass_1']:>6}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument("--gold-version", choices=("v1", "v2"), default="v1")
    args = ap.parse_args(argv)

    cases_by_id = load_gold(args.gold_version)
    per_case = load_jsonl(args.report)
    stats = compute_pass_at_n(per_case, cases_by_id, args.db)

    o = stats["overall"]
    print(f"{args.report}: {o['total']} ANSWER-expected cases")
    print(_line("overall", o))
    print(
        f"  outside the N candidates but correct (exec_error repair): "
        f"{o['winner_outside_pool_correct']}"
    )
    print()
    print(f"{'tier':<17} {'n':>3} {'pass@1':>13} {'pass@N':>13} {'gap':>6}")
    for tier, r in stats["by_tier"].items():
        print(_line(tier, r))
    print()
    print(f"winner drift vs recorded execution_correct: {len(stats['drift'])} case(s)")
    for d in stats["drift"]:
        flags = f"recorded={d['recorded']} local={d['local']}"
        print(f"  {d['id']} ({d['tier']}): {flags} -> {d['cause']}")
    print(f"recorded rows != local re-execution (DB drift): {stats['rows_drift'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
