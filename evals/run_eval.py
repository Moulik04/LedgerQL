"""Runs every case in evals/gold.jsonl through the real Phase 2 pipeline
and scores it -- distinct from evals/validate_gold.py, which only
validates that the gold SQL itself is well-formed and binds/executes;
this script actually exercises pipeline.ask() and compares its output
to gold.

Run: python evals/run_eval.py --db data/ledgerql.duckdb
Writes: reports/eval.md and reports/eval_<date>.jsonl
"""

from __future__ import annotations

import argparse
import json
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

from ledgerql import answer as answer_module
from ledgerql import generate as generate_module
from ledgerql import pipeline
from ledgerql.verify import verify as verify_answer

# The report header reads its temperature/N/threshold values directly from
# these modules' own constants (not hardcoded) so a future run with
# different env-var overrides reports its real values. answer_module's
# OLLAMA_TEMPERATURE is the actual answer-writing temperature;
# generate_module's OLLAMA_CONSENSUS_TEMPERATURE is what self-consistency
# candidate generation actually runs at -- these are two different
# temperatures, not one value reused for both (see DECISIONS.md).


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


GUARDRAIL_SCORED_TIERS = {"adversarial", "schema_bait", "out_of_scope"}


def score_guardrail_case(case: dict, result: dict) -> dict:
    blocked = result["answer"] is None
    reason_correct = result.get("reason_code") == case.get("reason_code")
    guardrail_tag = case.get("guardrail_must_fire")
    guardrail_ok = guardrail_tag is None or guardrail_tag in result.get("guardrail_events", [])
    return {
        "blocked": blocked,
        "reason_correct": reason_correct,
        "guardrail_ok": guardrail_ok,
        "passed": blocked and reason_correct and guardrail_ok,
    }


ABSTAIN_EXPECTED_BEHAVIORS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}


def compute_abstain_metrics(per_case: list[dict], cases_by_id: dict) -> dict:
    all_abstains = [r for r in per_case if r["answer"] is None]
    correct_abstains = [
        r
        for r in all_abstains
        if cases_by_id[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
        and r.get("reason_code") == cases_by_id[r["id"]].get("reason_code")
    ]
    expected_abstains = [
        c for c in cases_by_id.values() if c["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
    ]
    return {
        "all_abstains": len(all_abstains),
        "correct_abstains": len(correct_abstains),
        "expected_abstains": len(expected_abstains),
        "abstain_precision": len(correct_abstains) / len(all_abstains) if all_abstains else 0.0,
        "abstain_recall": (
            len(correct_abstains) / len(expected_abstains) if expected_abstains else 0.0
        ),
    }


def load_gold_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run(gold_path: Path, db_path: str) -> dict:
    cases = load_gold_cases(gold_path)
    cases_by_id = {c["id"]: c for c in cases}
    # Must match execute.execute()'s connection config exactly -- DuckDB
    # refuses a second connection to the same file with a different
    # config, even when both are read-only.
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})

    per_case = []
    tier_correct: dict[str, int] = defaultdict(int)
    tier_total: dict[str, int] = defaultdict(int)
    guardrail_correct: dict[str, int] = defaultdict(int)
    guardrail_total: dict[str, int] = defaultdict(int)
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
            "reason_code": result.get("reason_code"),
            "guardrail_events": result.get("guardrail_events", []),
            "confidence": result.get("confidence"),
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

        if case["tier"] in GUARDRAIL_SCORED_TIERS and case["expected"] == "ABSTAIN":
            score = score_guardrail_case(case, result)
            record["guardrail_score"] = score
            guardrail_total[case["tier"]] += 1
            if score["passed"]:
                guardrail_correct[case["tier"]] += 1

        if result["answer"] is not None:
            answered += 1
            # Reuse verify.py's own verify() directly -- the exact function
            # the live pipeline already ran against this same answer/result
            # pair -- rather than a second, independently-maintained
            # grounding check. A prior version of this block reimplemented
            # the comparison inline and silently drifted out of sync with a
            # real verify.py fix (pre-scaled query results, e.g. `value /
            # 1e9 AS revenue_in_billions`), causing this metric to flag
            # answers as hallucinated that the live pipeline had already
            # correctly verified as grounded.
            verify_result = verify_answer(result["answer"], result["columns"], result["rows"])
            record["hallucinated_numbers"] = verify_result.ungrounded_numbers
            if not verify_result.ok:
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

    abstain_metrics = compute_abstain_metrics(per_case, cases_by_id)

    return {
        "overall_execution_accuracy": overall_accuracy,
        "all_tiers": all_tiers,
        "per_tier_accuracy": {tier: tier_correct[tier] / tier_total[tier] for tier in tier_total},
        "guardrail_catch_rate": {
            tier: guardrail_correct[tier] / guardrail_total[tier] for tier in guardrail_total
        },
        "hallucinated_number_rate": hallucinated / answered if answered else 0.0,
        "answered_count": answered,
        "non_answer_case_count": len(non_answer_cases),
        "non_answer_attempted": non_answer_attempted,
        "non_answer_errored": non_answer_errored,
        "non_answer_tier_breakdown": non_answer_tier_breakdown,
        "per_case": per_case,
        **abstain_metrics,
    }


def write_reports(summary: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = reports_dir / "eval.md"
    jsonl_path = reports_dir / f"eval_{today}.jsonl"

    with jsonl_path.open("w") as f:
        for record in summary["per_case"]:
            # rows/gold rows can carry DuckDB-native types (date, Decimal, ...)
            # that json can't serialize natively; stringify anything it can't.
            f.write(json.dumps(record, default=str) + "\n")

    lines = [
        "# LedgerQL Eval",
        "",
        f"Date: {today}",
        f"Model: {generate_module.OLLAMA_MODEL}",
        f"Candidate temperature: {generate_module.OLLAMA_CONSENSUS_TEMPERATURE}",
        f"Answer temperature: {answer_module.OLLAMA_TEMPERATURE}",
        f"Seed: {generate_module.OLLAMA_SEED}",
        f"Candidates per question (N): {pipeline.N_CANDIDATES}",
        f"Low-agreement threshold: {pipeline.LOW_AGREEMENT_THRESHOLD}",
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
        "This checks the answer against its own query's result set, not "
        "against the gold SQL -- it catches the model inventing or "
        "mistranscribing a number, not the model answering a different "
        "question than the one asked. A wrong-but-self-consistent SQL "
        "query (e.g. an exact-match filter where gold uses a fuzzy one, "
        "or a different date column) can still score 0% hallucinated: "
        "every number it states really is in its own result, that result "
        "is just an answer to the wrong query. That failure mode shows up "
        "in execution accuracy, not here.",
        "",
        "## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)",
        "",
        f"{summary['non_answer_case_count']} cases where a guardrail-aware "
        "system should abstain or state an assumption. This section is "
        "descriptive (raw attempted/errored counts, not a pass/fail "
        "score) -- the Confidence & abstain section below is where "
        "abstain behavior is actually scored (precision/recall):",
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
        "## Guardrail catch rate",
        "",
        "Adversarial-tier target: 100% (Phase 3 acceptance criterion).",
        "",
        "| Tier | Catch rate |",
        "|---|---|",
    ]
    for tier in sorted(GUARDRAIL_SCORED_TIERS):
        rate = summary["guardrail_catch_rate"].get(tier)
        lines.append(f"| {tier} | {rate:.1%} |" if rate is not None else f"| {tier} | no cases |")
    lines += [
        "",
        "## Confidence & abstain",
        "",
        f"Abstain precision: {summary['abstain_precision']:.1%} "
        f"({summary['correct_abstains']}/{summary['all_abstains']} abstains were correct) "
        "-- Phase 4 acceptance target: >= 80%.",
        f"Abstain recall: {summary['abstain_recall']:.1%} "
        f"({summary['correct_abstains']}/{summary['expected_abstains']} cases that should "
        "have abstained were caught).",
        "",
        "## Ablation",
        "",
        "| Configuration | Execution accuracy | Hallucinated-number rate "
        "| Adversarial guardrail catch |",
        "|---|---|---|---|",
        "| naive (Phase 2) | 58.0% | 32.5% | n/a |",
        "| +static guardrails (Phase 3) | 58.0% | 28.6% | 88.9% |",
        f"| +self-consistency & verifier (Phase 4) | {summary['overall_execution_accuracy']:.1%} "
        f"| {summary['hallucinated_number_rate']:.1%} "
        f"| {summary['guardrail_catch_rate'].get('adversarial', 0.0):.1%} |",
    ]
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
