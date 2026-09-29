"""Replay a measured report under the year-grounding verifier, no GPU needed.

`verify.verify` now requires every year in an answer's prose to appear in a
result cell or as a literal in the executed SQL (DECISIONS.md, 2026-09-29; before
that a year was only checked when the result had a `fiscal_year` column). Every
answered record carries the answer, the result and the executed SQL, so the rule
can be re-applied exactly: an answer it rejects becomes what
`pipeline._answer_from` produces for a rejected answer, an `UNGROUNDED_ANSWER`
abstain with the result attached, and all metrics are recomputed from those
records by `replay_repair_off.summarize`.

Composes with the repair cut: the shipped config is `revert_exec_error_repairs`
first, then this.

    python -m evals.replay_year_rule reports/eval_bridges2_qwen3_30b_measured.jsonl
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evals.passn_scoring import GOLD_PATH, load_jsonl
from evals.replay_repair_off import revert_exec_error_repairs, summarize
from ledgerql import verify


def _rejected(record: dict) -> bool:
    if record["answer"] is None:
        return False
    result = verify.verify(
        record["answer"], record["columns"], record["rows"], sql=record.get("generated_sql")
    )
    return not result.ok


def _abstained(record: dict) -> dict:
    """What `pipeline._answer_from` returns when the verifier rejects an answer."""
    out = dict(record)
    out["answer"] = None
    out["reason_code"] = "UNGROUNDED_ANSWER"
    out["columns"] = []
    out["rows"] = []
    out["truncated"] = False
    out.pop("hallucinated_numbers", None)
    if record["expected"] in ("ANSWER", "ANSWER_WITH_ASSUMPTION"):
        out["execution_correct"] = False
    else:
        out.pop("execution_correct", None)
    return out


def apply_year_rule(per_case: list[dict]) -> list[dict]:
    return [_abstained(r) if _rejected(r) else r for r in per_case]


def year_rule_flags(per_case: list[dict]) -> list[str]:
    return sorted(r["id"] for r in per_case if _rejected(r))


def _rows(label_a: str, a: dict, label_b: str, b: dict) -> list[tuple[str, str, str]]:
    def pct(x):
        return f"{x:.1%}"

    return [
        ("answered", str(a["answered_count"]), str(b["answered_count"])),
        ("execution accuracy (ANSWER)", pct(a["overall_execution_accuracy"]),
         pct(b["overall_execution_accuracy"])),
        ("confidently-wrong rate", pct(a["confidently_wrong_rate"]),
         pct(b["confidently_wrong_rate"])),
        ("confidently-wrong count", str(a["confidently_wrong_count"]),
         str(b["confidently_wrong_count"])),
        ("abstain precision, decision", pct(a["abstain_precision_decision"]),
         pct(b["abstain_precision_decision"])),
        ("abstain recall, decision", pct(a["abstain_recall_decision"]),
         pct(b["abstain_recall_decision"])),
    ]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports", nargs="+", type=Path)
    args = ap.parse_args(argv)
    cases = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    for path in args.reports:
        shipped = revert_exec_error_repairs(load_jsonl(path))
        flagged = year_rule_flags(shipped)
        after = apply_year_rule(shipped)
        a, b = summarize(shipped, cases), summarize(after, cases)
        n = a["answered_count"]
        print(f"\n== {path.name}: shipped config, before -> after the year rule")
        print(
            f"  answers the rule rejects: {len(flagged)} of {n} ({len(flagged) / n:.1%}): {flagged}"
        )
        print(f"  {'metric':<32} {'before':>8} {'after':>8}")
        for name, x, y in _rows("before", a, "after", b):
            print(f"  {name:<32} {x:>8} {y:>8}")
        print(
            f"  hallucinated-number rate, non-year numbers only: "
            f"{a['hallucinated_number_rate']:.1%} -> {b['hallucinated_number_rate']:.1%}"
        )
        print(
            f"  hallucinated rate INCLUDING years: {len(flagged) / n:.1%} -> "
            f"{0 / b['answered_count']:.1%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
