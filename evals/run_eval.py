"""Runs every case in evals/gold.jsonl through the real Phase 2 pipeline
and scores it -- distinct from evals/validate_gold.py, which only
validates that the gold SQL itself is well-formed and binds/executes;
this script actually exercises pipeline.ask() and compares its output
to gold.

Run: python evals/run_eval.py --db data/ledgerql.duckdb
Writes: reports/baseline.md and reports/baseline_<date>.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from ledgerql import generate as generate_module
from ledgerql import pipeline

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# A bare 4-digit number that reads as a plausible fiscal/calendar year
# (2000-2099) is excluded -- these appear constantly in grounded,
# correct answers ("fiscal year 2024") and are not data values that
# need to trace back to the executed result set.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        raw_digits, word = match.groups()
        digits = raw_digits.replace(",", "")
        if not word and _YEAR_RE.match(digits):
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        if word and word.lower() in _MAGNITUDE:
            value *= _MAGNITUDE[word.lower()]
        numbers.append(value)
    return numbers


def _scalar_match(gold_val, pred_val, tolerance: float) -> bool:
    if gold_val is None or pred_val is None:
        return gold_val == pred_val
    try:
        return abs(float(pred_val) - float(gold_val)) <= max(abs(float(gold_val)) * tolerance, 1e-9)
    except (TypeError, ValueError):
        return gold_val == pred_val


def results_match(
    gold_rows: list[tuple], pred_rows: list[tuple], compare: str, tolerance: float = 1e-6
) -> bool:
    if compare == "empty":
        return len(pred_rows) == 0
    if compare in ("scalar", "count", "scalar_or_null"):
        if len(pred_rows) != 1 or len(pred_rows[0]) != 1:
            return False
        gold_val = gold_rows[0][0] if gold_rows else None
        return _scalar_match(gold_val, pred_rows[0][0], tolerance)
    if compare == "set":
        return set(map(tuple, gold_rows)) == set(map(tuple, pred_rows))
    if compare == "ordered":
        return list(map(tuple, gold_rows)) == list(map(tuple, pred_rows))
    raise ValueError(f"unknown compare value: {compare!r}")


def load_gold_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run(gold_path: Path, db_path: str) -> dict:
    cases = load_gold_cases(gold_path)
    con = duckdb.connect(db_path, read_only=True)

    per_case = []
    tier_correct: dict[str, int] = defaultdict(int)
    tier_total: dict[str, int] = defaultdict(int)
    hallucinated = 0
    answered = 0

    for case in cases:
        result = pipeline.ask(case["question"])
        record = {
            "id": case["id"],
            "tier": case["tier"],
            "expected": case["expected"],
            "generated_sql": result["sql"],
            "execution_error": result["error"],
            "answer": result["answer"],
        }

        if case["expected"] == "ANSWER":
            tier_total[case["tier"]] += 1
            correct = False
            if result["error"] is None:
                gold_rows = con.execute(case["gold_sql"]).fetchall()
                tolerance = case.get("tolerance", 1e-6)
                correct = results_match(gold_rows, result["rows"], case["compare"], tolerance)
            record["execution_correct"] = correct
            if correct:
                tier_correct[case["tier"]] += 1

        if result["answer"]:
            answered += 1
            claimed = extract_numbers(result["answer"])
            grounded_values = {
                v for row in result["rows"] for v in row if isinstance(v, int | float)
            }
            ungrounded = [
                n for n in claimed if not any(_scalar_match(g, n, 0.01) for g in grounded_values)
            ]
            record["hallucinated_numbers"] = ungrounded
            if ungrounded:
                hallucinated += 1

        per_case.append(record)

    con.close()

    answer_cases = [c for c in cases if c["expected"] == "ANSWER"]
    overall_accuracy = sum(tier_correct.values()) / len(answer_cases) if answer_cases else 0.0
    non_answer_cases = [c for c in cases if c["expected"] != "ANSWER"]
    non_answer_records = [r for r in per_case if r["expected"] != "ANSWER"]
    non_answer_attempted = sum(1 for r in non_answer_records if r["answer"] is not None)
    non_answer_errored = sum(1 for r in non_answer_records if r["execution_error"] is not None)

    return {
        "overall_execution_accuracy": overall_accuracy,
        "per_tier_accuracy": {tier: tier_correct[tier] / tier_total[tier] for tier in tier_total},
        "hallucinated_number_rate": hallucinated / answered if answered else 0.0,
        "answered_count": answered,
        "non_answer_case_count": len(non_answer_cases),
        "non_answer_attempted": non_answer_attempted,
        "non_answer_errored": non_answer_errored,
        "per_case": per_case,
    }


def write_reports(summary: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = reports_dir / "baseline.md"
    jsonl_path = reports_dir / f"baseline_{today}.jsonl"

    with jsonl_path.open("w") as f:
        for record in summary["per_case"]:
            f.write(json.dumps(record) + "\n")

    lines = [
        "# Phase 2 Baseline",
        "",
        f"Date: {today}",
        f"Model: {generate_module.OLLAMA_MODEL}",
        "",
        "## Execution accuracy",
        "",
        f"Overall (on 'ANSWER'-expected cases): " f"{summary['overall_execution_accuracy']:.1%}",
        "",
        "| Tier | Accuracy |",
        "|---|---|",
    ]
    for tier, acc in sorted(summary["per_tier_accuracy"].items()):
        lines.append(f"| {tier} | {acc:.1%} |")
    lines += [
        "",
        "## Hallucinated-number rate",
        "",
        f"{summary['hallucinated_number_rate']:.1%} of "
        f"{summary['answered_count']} answered cases stated a number not "
        "present in that query's own executed result.",
        "",
        "## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)",
        "",
        f"{summary['non_answer_case_count']} cases where a guardrail-aware "
        "system should abstain or state an assumption. Phase 2 has no "
        "abstain logic, so this section is descriptive, not scored:",
        "",
        f"- Attempted an answer anyway: {summary['non_answer_attempted']}",
        f"- Errored during execution (e.g. adversarial DML hitting the "
        f"read-only connection): {summary['non_answer_errored']}",
        "",
        f"Full per-case results: `{jsonl_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines))
    return md_path, jsonl_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    args = ap.parse_args()

    summary = run(Path(args.gold), args.db)
    md_path, jsonl_path = write_reports(summary, Path("reports"))
    print(f"Wrote {md_path} and {jsonl_path}")
    print(f"Overall execution accuracy: {summary['overall_execution_accuracy']:.1%}")
    print(f"Hallucinated-number rate: {summary['hallucinated_number_rate']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
