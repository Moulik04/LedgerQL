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

# Ensure the project root (this file's parent directory) is importable when
# this script is run directly (`python evals/run_eval.py`), which sets
# sys.path[0] to evals/ rather than the project root. Normally the editable
# install (`uv sync`) makes `ledgerql` importable without this, but that
# depends on the interpreter processing the editable-install .pth file in
# site-packages, and on at least one real machine that step was silently
# skipped by CPython 3.12's site.py (which refuses to read a .pth file that
# carries the macOS "hidden" (UF_HIDDEN) file flag) -- so `ledgerql` was not
# importable even though `uv sync` reported everything installed correctly.
# This bootstrap makes the script self-sufficient regardless of that.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerql import generate as generate_module
from ledgerql import pipeline

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# A bare 4-digit number that reads as a plausible fiscal/calendar year
# (2000-2099) is excluded -- these appear constantly in grounded,
# correct answers ("fiscal year 2024") and are not data values that
# need to trace back to the executed result set.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(-?\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")
# A bare number immediately followed by a hyphen and an uppercase letter
# is an SEC form code (e.g. "10-K", "10-Q"), not a data value.
_FORM_CODE_RE = re.compile(r"-[A-Z]")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        if _FORM_CODE_RE.match(text, match.end()):
            continue
        raw_digits, word = match.groups()
        # Strip a trailing sentence period (e.g. "fiscal year 2024.")
        # before the year-exclusion check and float conversion, so a
        # number followed immediately by a period is treated the same
        # as one that stands alone.
        digits = raw_digits.replace(",", "").rstrip(".")
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
    if compare == "none":
        return True
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
    # Must match execute.execute()'s connection config exactly -- DuckDB
    # refuses a second connection to the same file with a different
    # config, even when both are read-only.
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})

    per_case = []
    tier_correct: dict[str, int] = defaultdict(int)
    tier_total: dict[str, int] = defaultdict(int)
    hallucinated = 0
    answered = 0

    for case in cases:
        try:
            result = pipeline.ask(case["question"], db_path=db_path)
        except Exception as e:  # noqa: BLE001
            # A single pipeline crash (e.g. a transient Ollama hiccup) over
            # 103 real LLM calls must not discard every already-computed
            # result for prior cases -- record a minimal failure and move on.
            per_case.append(
                {
                    "id": case["id"],
                    "tier": case["tier"],
                    "expected": case["expected"],
                    "generated_sql": None,
                    "execution_error": f"pipeline crashed: {e}",
                    "answer": None,
                }
            )
            if case["expected"] == "ANSWER":
                tier_total[case["tier"]] += 1
            continue

        record = {
            "id": case["id"],
            "tier": case["tier"],
            "expected": case["expected"],
            "generated_sql": result["sql"],
            "execution_error": result["error"],
            "answer": result["answer"],
            "columns": result["columns"],
            "rows": result["rows"],
            "truncated": result["truncated"],
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

        if result["answer"] is not None:
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

    all_tiers = sorted({case["tier"] for case in cases})
    answer_cases = [c for c in cases if c["expected"] == "ANSWER"]
    overall_accuracy = sum(tier_correct.values()) / len(answer_cases) if answer_cases else 0.0
    non_answer_cases = [c for c in cases if c["expected"] != "ANSWER"]
    non_answer_records = [r for r in per_case if r["expected"] != "ANSWER"]
    non_answer_attempted = sum(1 for r in non_answer_records if r["answer"] is not None)
    non_answer_errored = sum(1 for r in non_answer_records if r["execution_error"] is not None)

    non_answer_tier_breakdown: dict[str, dict[str, int]] = {}
    for tier in sorted({r["tier"] for r in non_answer_records}):
        tier_records = [r for r in non_answer_records if r["tier"] == tier]
        non_answer_tier_breakdown[tier] = {
            "attempted": sum(1 for r in tier_records if r["answer"] is not None),
            "errored": sum(1 for r in tier_records if r["execution_error"] is not None),
        }

    return {
        "overall_execution_accuracy": overall_accuracy,
        "all_tiers": all_tiers,
        "per_tier_accuracy": {tier: tier_correct[tier] / tier_total[tier] for tier in tier_total},
        "hallucinated_number_rate": hallucinated / answered if answered else 0.0,
        "answered_count": answered,
        "non_answer_case_count": len(non_answer_cases),
        "non_answer_attempted": non_answer_attempted,
        "non_answer_errored": non_answer_errored,
        "non_answer_tier_breakdown": non_answer_tier_breakdown,
        "per_case": per_case,
    }


def write_reports(summary: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = reports_dir / "baseline.md"
    jsonl_path = reports_dir / f"baseline_{today}.jsonl"

    with jsonl_path.open("w") as f:
        for record in summary["per_case"]:
            # rows/gold rows can carry DuckDB-native types (date, Decimal, ...)
            # that json can't serialize natively; stringify anything it can't.
            f.write(json.dumps(record, default=str) + "\n")

    lines = [
        "# Phase 2 Baseline",
        "",
        f"Date: {today}",
        f"Model: {generate_module.OLLAMA_MODEL}",
        f"Temperature: {generate_module.OLLAMA_TEMPERATURE}",
        f"Seed: {generate_module.OLLAMA_SEED}",
        "",
        "## Execution accuracy",
        "",
        f"Overall (on 'ANSWER'-expected cases): " f"{summary['overall_execution_accuracy']:.1%}",
        "",
        "| Tier | Accuracy |",
        "|---|---|",
    ]
    per_tier_accuracy = summary["per_tier_accuracy"]
    for tier in summary["all_tiers"]:
        if tier in per_tier_accuracy:
            lines.append(f"| {tier} | {per_tier_accuracy[tier]:.1%} |")
        else:
            lines.append(f"| {tier} | no positive control in this tier |")
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
        "### Per-tier breakdown of non-ANSWER outcomes",
        "",
        "| Tier | Attempted anyway | Errored |",
        "|---|---|---|",
    ]
    for tier, counts in sorted(summary["non_answer_tier_breakdown"].items()):
        lines.append(f"| {tier} | {counts['attempted']} | {counts['errored']} |")
    lines += [
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
