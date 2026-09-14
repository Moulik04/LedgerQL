"""Diagnose why a real eval run's abstains were right or wrong.

`run_eval.py`'s own `compute_abstain_metrics()` scores abstain precision
against an exact reason_code match, which conflates several genuinely
different failure modes into one number -- this tool breaks a real run's
abstains back out into those modes, the same categories worked out by hand
(inline `python3 -c` investigation) during Phase 4 and Phase 5's real
end-to-end runs (see DECISIONS.md's 2026-09-11 and 2026-09-14 entries):

- correct: reason_code matches gold's exactly.
- structurally unreachable: gold's own reason_code (AMBIGUOUS, NO_DATA, or
  no reason_code at all for an ANSWER_WITH_ASSUMPTION case) is not one the
  Core-only pipeline can ever produce -- no code fix makes these "correct."
- reachable miss: gold's reason_code is one the pipeline really can
  produce, but this run produced a different one -- a genuine, fixable-in-
  principle miss.
- shouldn't have abstained: the gold case expected a plain ANSWER, grouped
  by which reason_code triggered the abstain.
- missed abstain: the gold case expected an abstain, but the pipeline
  answered instead (the recall-side failure, not scored by precision at
  all).

Run: python evals/diagnose_abstains.py reports/eval_<date>.jsonl --gold evals/gold.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# The only reason codes the Core-only pipeline can actually produce --
# confirmed by reading every reason_code= call site in classify.py,
# guardrails.py, and pipeline.py. AMBIGUOUS/NO_DATA only exist in gold.jsonl
# because it was authored against the fuller statistical-calibration
# framework evals/README.md describes, which this phase explicitly deferred
# (see DECISIONS.md, 2026-09-11). Update this set if a future phase adds a
# new reason_code to the pipeline itself.
REACHABLE_REASON_CODES = {
    "OUT_OF_SCOPE",
    "SCHEMA_MISMATCH",
    "COST_LIMIT",
    "EXEC_ERROR",
    "LOW_AGREEMENT",
    "UNGROUNDED_ANSWER",
}

ABSTAIN_EXPECTED_BEHAVIORS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}


def categorize_abstains(records: list[dict], gold_by_id: dict[str, dict]) -> dict:
    correct: list[str] = []
    structurally_unreachable: list[str] = []
    reachable_miss: list[str] = []
    shouldnt_have_abstained: dict[str, list[str]] = {}
    missed_abstain: list[str] = []

    for record in records:
        case_id = record["id"]
        gold = gold_by_id[case_id]
        expected = gold["expected"]
        gold_reason = gold.get("reason_code")
        got_reason = record.get("reason_code")
        abstained = record["answer"] is None

        if expected in ABSTAIN_EXPECTED_BEHAVIORS:
            if not abstained:
                missed_abstain.append(case_id)
            elif got_reason == gold_reason:
                correct.append(case_id)
            elif gold_reason not in REACHABLE_REASON_CODES:
                structurally_unreachable.append(case_id)
            else:
                reachable_miss.append(case_id)
        elif abstained:
            shouldnt_have_abstained.setdefault(got_reason, []).append(case_id)

    return {
        "correct": correct,
        "structurally_unreachable": structurally_unreachable,
        "reachable_miss": reachable_miss,
        "shouldnt_have_abstained": shouldnt_have_abstained,
        "missed_abstain": missed_abstain,
    }


def format_report(categories: dict) -> str:
    lines = [
        f"correct: {len(categories['correct'])} ({', '.join(categories['correct']) or '-'})",
        f"structurally unreachable: {len(categories['structurally_unreachable'])} "
        f"({', '.join(categories['structurally_unreachable']) or '-'})",
        f"reachable miss: {len(categories['reachable_miss'])} "
        f"({', '.join(categories['reachable_miss']) or '-'})",
        "shouldn't have abstained, by reason code:",
    ]
    for reason, ids in sorted(categories["shouldnt_have_abstained"].items()):
        lines.append(f"  {reason}: {len(ids)} ({', '.join(ids)})")
    lines.append(
        "missed abstain (answered when it should have abstained): "
        f"{len(categories['missed_abstain'])} ({', '.join(categories['missed_abstain']) or '-'})"
    )
    return "\n".join(lines)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_jsonl", help="Path to a reports/eval_<date>.jsonl file")
    parser.add_argument("--gold", required=True, help="Path to evals/gold.jsonl")
    args = parser.parse_args(argv)

    records = load_jsonl(Path(args.report_jsonl))
    gold_by_id = {case["id"]: case for case in load_jsonl(Path(args.gold))}

    categories = categorize_abstains(records, gold_by_id)
    print(format_report(categories))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
