"""Replay a measured report's headline metrics with the ``exec_error`` repair
trigger counterfactually off -- exact, no GPU needed.

``exec_error`` was cut 2026-09-21 (DECISIONS.md, ``ledgerql/repair.py``): net
negative on the 30B Bridges-2 run, more required abstains converted to wrong
answers than answers rescued correctly. This reconstructs, for a report
measured while the trigger was still on, exactly what each repaired record
would have looked like had it never fired -- not an estimate: every field this
needs (the failure's reason code, whether the failure carried a message) is
determined by the trigger itself, and ``ledgerql/pipeline.ask()``'s own
``trigger is None`` branch (the code path this now always takes) is what
``_reverted_record`` reproduces.

Only records whose ``repair`` was attempted via the ``exec_error`` trigger are
touched. ``schema_mismatch`` was never enabled for a measured run, so no record
in a Bridges-2 report carries it. Everything else in the report -- routing that
had nothing to do with repair -- is untouched.

Usage: ``python -m evals.replay_repair_off reports/<measured>.jsonl``
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evals.abstain_scoring import compute_abstain_metrics
from evals.repair_scoring import compute_repair_stats
from ledgerql.repair import EXEC_ERROR_TRIGGER

GOLD_PATH = Path(__file__).resolve().parent / "gold.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _reverted_record(record: dict) -> dict:
    """What this record would be had ``exec_error`` repair never been
    attempted: ``pipeline.ask()``'s ``trigger is None`` branch, which every
    ``exec_error``-triggered failure now takes (the trigger set that reaches
    ``repair.failure_trigger`` maps only ``EXEC_ERROR`` -> ``exec_error``, so
    the pre-repair reason code is always ``EXEC_ERROR``)."""
    reverted = dict(record)
    reverted["reason_code"] = "EXEC_ERROR"
    reverted["answer"] = None
    reverted["columns"] = []
    reverted["rows"] = []
    reverted["truncated"] = False
    reverted["confidence"] = None
    reverted["repair"] = None
    reverted.pop("hallucinated_numbers", None)
    if record["expected"] in ("ANSWER", "ANSWER_WITH_ASSUMPTION"):
        reverted["execution_correct"] = False
    else:
        reverted.pop("execution_correct", None)
    return reverted


def revert_exec_error_repairs(per_case: list[dict]) -> list[dict]:
    return [
        _reverted_record(r) if (r.get("repair") or {}).get("trigger") == EXEC_ERROR_TRIGGER else r
        for r in per_case
    ]


def summarize(per_case: list[dict], cases_by_id: dict) -> dict:
    """The subset of run_eval.py's ``run()`` aggregation that depends only on
    fields already present in a per-case record (not on re-executing gold SQL,
    which every record here already carries ``execution_correct`` for)."""
    tier_correct: dict[str, int] = defaultdict(int)
    tier_total: dict[str, int] = defaultdict(int)
    hallucinated = 0
    answered = 0
    for record in per_case:
        case = cases_by_id[record["id"]]
        if case["expected"] == "ANSWER":
            tier_total[case["tier"]] += 1
            if record.get("execution_correct") is True:
                tier_correct[case["tier"]] += 1
        if record["answer"] is not None:
            answered += 1
            if record.get("hallucinated_numbers"):
                hallucinated += 1

    answer_cases = [c for c in cases_by_id.values() if c["expected"] == "ANSWER"]
    overall_accuracy = sum(tier_correct.values()) / len(answer_cases) if answer_cases else 0.0

    return {
        "overall_execution_accuracy": overall_accuracy,
        "hallucinated_number_rate": hallucinated / answered if answered else 0.0,
        "answered_count": answered,
        "repair": compute_repair_stats(per_case, cases_by_id),
        **compute_abstain_metrics(per_case, cases_by_id),
    }


def _fmt_pct(x: float) -> str:
    return f"{x:.1%}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    args = ap.parse_args(argv)

    cases_by_id = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    measured = load_jsonl(args.report)
    reverted = revert_exec_error_repairs(measured)

    touched = [r["id"] for r, m in zip(reverted, measured, strict=True) if r is not m]
    print(f"{args.report}: {len(measured)} records, {len(touched)} exec_error-repaired: {touched}")

    before, after = summarize(measured, cases_by_id), summarize(reverted, cases_by_id)
    rows = [
        ("execution accuracy", "overall_execution_accuracy"),
        ("hallucinated-number rate", "hallucinated_number_rate"),
        ("abstain precision, decision", "abstain_precision_decision"),
        ("abstain precision, strict", "abstain_precision_strict"),
        ("abstain recall, decision", "abstain_recall_decision"),
        ("abstain recall, strict", "abstain_recall_strict"),
        ("reason-code accuracy", "reason_code_accuracy"),
    ]
    print(f"{'metric':<30} {'shipped (repair off)':>22} {'measured (repair on)':>22}")
    for label, key in rows:
        print(f"{label:<30} {_fmt_pct(after[key]):>22} {_fmt_pct(before[key]):>22}")
    print(f"{'answered':<30} {after['answered_count']:>22} {before['answered_count']:>22}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
