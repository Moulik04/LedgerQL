"""Audit of `results_match` against over-specified gold.

Some gold queries return context columns beside the value being asked for
(`fiscal_year`, `period_end_date`, `uom`) so that an `ANSWER_WITH_ASSUMPTION`
answer can state which period it means. `run_eval.results_match` compares whole
result sets, so a model that returns exactly the right value without those
columns is scored wrong. U02 is the example: Apple's fiscal-2024 revenue,
correct to the digit, fails `compare: set` against gold `(value, period_end_date)`.
That is a property of the gold design, not a pipeline fault, and it makes
execution accuracy under-report.

This measures how many cases it affects, and what accuracy would be under a
relaxed rule, without changing any scoring:

- A gold column is *context* if its name is one of CONTEXT_NAMES **and** it is
  constant across gold's rows. Constancy matters: in a multi-year series
  `fiscal_year` labels which value belongs to which year, so it is part of the
  answer and stays required.
- Under the relaxed rule the context columns are dropped from gold, and any
  context-named model column that gold does not require is dropped from the
  prediction (a model may add `fiscal_year` even if gold has no such column); the remaining
  target columns are compared with the case's own `compare` mode. A model that
  aliases a context column (`year`) is not matched by name and stays a mismatch.
- Whether the assumption was *stated* is `answer_must_state`, which nothing
  scores yet (evals/README.md section 3); the relaxed rule does not pretend to.

    python -m evals.comparator_audit reports/eval_bridges2_qwen3_30b_measured.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from evals.abstain_scoring import compute_abstain_metrics
from evals.passn_scoring import GOLD_PATH, load_jsonl
from evals.replay_repair_off import revert_exec_error_repairs
from evals.replay_year_rule import apply_year_rule
from evals.run_eval import results_match
from evals.year_audit import audit as year_audit

CONTEXT_NAMES = {"fiscal_year", "period_end_date", "uom", "fiscal_period"}
_SCORED = ("ANSWER", "ANSWER_WITH_ASSUMPTION")


def context_columns(columns: list[str], rows: list) -> set[int]:
    """Indexes of gold columns that are context: context-named and constant across
    rows. A gold result made only of context columns keeps them all."""
    idx = {
        i
        for i, name in enumerate(columns)
        if name.lower() in CONTEXT_NAMES and len({tuple([row[i]]) for row in rows}) <= 1
    }
    return set() if len(idx) == len(columns) else idx


def _project(columns: list[str], rows: list, drop: set[int] | set[str], by_name: bool) -> list:
    keep = [
        i
        for i, name in enumerate(columns)
        if (name.lower() not in drop if by_name else i not in drop)
    ]
    return [tuple(row[i] for i in keep) for row in rows]


def relaxed_match(
    case: dict, gold_cols: list[str], gold_rows: list, pred_cols: list[str], pred_rows: list
) -> bool:
    drop = context_columns(gold_cols, gold_rows)
    kept_names = {name.lower() for i, name in enumerate(gold_cols) if i not in drop}
    # A prediction may carry any context-named column gold does not require.
    dropped_names = CONTEXT_NAMES - kept_names
    gold_target = _project(gold_cols, gold_rows, drop, by_name=False)
    pred_target = _project(pred_cols, pred_rows, dropped_names, by_name=True)
    return results_match(gold_target, pred_target, case["compare"], case.get("tolerance", 1e-6))


def gold_results(cases: dict, db_path: str) -> dict[str, tuple[list[str], list[tuple]]]:
    """Gold columns and rows per scored case, normalised the way reports store
    results (json with default=str), so dates compare as the strings they were
    recorded as."""
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    out = {}
    try:
        for cid, case in cases.items():
            if case["expected"] in _SCORED and case.get("gold_sql"):
                cur = con.execute(case["gold_sql"])
                rows = json.loads(json.dumps(cur.fetchall(), default=str))
                out[cid] = ([d[0] for d in cur.description], [tuple(r) for r in rows])
    finally:
        con.close()
    return out


def _scored(per_case: list[dict], cases: dict, gold: dict):
    for rec in per_case:
        case = cases.get(rec["id"])
        if case is not None and rec["id"] in gold and rec.get("answer") is not None:
            yield rec, case, gold[rec["id"]]


def strict_matches_recorded(per_case: list[dict], cases: dict, gold: dict) -> list[str]:
    """Ids where recomputing the strict rule from a record's own columns and rows
    disagrees with its recorded `execution_correct`. Empty means the audit and the
    eval agree."""
    bad = []
    for rec, case, (_, gold_rows) in _scored(per_case, cases, gold):
        rows = [tuple(r) for r in rec["rows"]]
        strict = results_match(gold_rows, rows, case["compare"], case.get("tolerance", 1e-6))
        if strict != (rec.get("execution_correct") is True):
            bad.append(rec["id"])
    return bad


def audit(per_case: list[dict], cases: dict, gold: dict) -> dict:
    context_only, breaks = [], []
    for rec, case, (gold_cols, gold_rows) in _scored(per_case, cases, gold):
        pred_rows = [tuple(r) for r in rec["rows"]]
        strict = rec.get("execution_correct") is True
        relaxed = relaxed_match(case, gold_cols, gold_rows, rec["columns"], pred_rows)
        if relaxed and not strict:
            context_only.append(rec["id"])
        if strict and not relaxed:
            breaks.append(rec["id"])
    by_expected = {}
    for expected in _SCORED:
        ids = [r for r in per_case if cases.get(r["id"], {}).get("expected") == expected]
        strict_n = sum(r.get("execution_correct") is True for r in ids)
        extra = sum(r["id"] in context_only for r in ids)
        by_expected[expected] = {"n": len(ids), "strict": strict_n, "relaxed": strict_n + extra}
    return {
        "context_only": context_only,
        "relaxed_breaks_correct": breaks,
        "strict_correct": sum(v["strict"] for v in by_expected.values()),
        "relaxed_correct": sum(v["relaxed"] for v in by_expected.values()),
        "by_expected": by_expected,
    }


def apply_relaxed(per_case: list[dict], context_only: list[str]) -> list[dict]:
    """The records as they would score if the context-only mismatches counted as
    correct. Nothing else about a record changes."""
    ids = set(context_only)
    return [{**r, "execution_correct": True} if r["id"] in ids else r for r in per_case]


def combined_rule(per_case: list[dict], cases: dict, gold: dict) -> dict:
    """The three changes adopted together: the year-grounding verifier (an answer
    it rejects abstains), then the relaxed comparator on what still answers.
    `answer_must_state` is not part of it: nothing scores that yet, so the result
    is an upper bound on assumption handling under the full rule."""
    after_years = apply_year_rule(per_case)
    credited = audit(after_years, cases, gold)["context_only"]
    return {"credited": credited, "records": apply_relaxed(after_years, credited)}


def assumption_outcomes(per_case: list[dict], cases: dict) -> dict:
    """`ANSWER_WITH_ASSUMPTION` cases split three ways. `assumption_case_handling`
    counts an abstain as handled, so a rule that turns wrong answers into abstains
    raises it while answering nothing better; this keeps them apart."""
    records = [r for r in per_case if cases[r["id"]]["expected"] == "ANSWER_WITH_ASSUMPTION"]
    abstained = sum(r["answer"] is None for r in records)
    correct = sum(r["answer"] is not None and r.get("execution_correct") is True for r in records)
    return {
        "answered_correct": correct,
        "abstained": abstained,
        "answered_wrong": len(records) - abstained - correct,
        "n": len(records),
    }


def gold_context_cases(cases: dict, gold: dict) -> list[tuple[str, list[str]]]:
    """Gold cases that carry at least one context column, with those columns."""
    found = []
    for cid, (cols, rows) in gold.items():
        drop = context_columns(cols, rows)
        if drop:
            found.append((cid, [cols[i] for i in sorted(drop)]))
    return found


def _report(label: str, per_case: list[dict], cases: dict, gold: dict) -> None:
    a = audit(per_case, cases, gold)
    print(f"\n== {label}")
    print(f"  fail strictly, pass on the target value alone: {len(a['context_only'])}")
    print(f"    {a['context_only']}")
    for expected, v in a["by_expected"].items():
        print(
            f"  {expected:<24} n={v['n']:>2}  strict {v['strict']:>2} -> relaxed {v['relaxed']:>2}"
        )
    n = a["by_expected"]["ANSWER"]["n"]
    s, r = a["by_expected"]["ANSWER"]["strict"], a["by_expected"]["ANSWER"]["relaxed"]
    print(f"  execution accuracy (ANSWER, the headline population): {s / n:.1%} -> {r / n:.1%}")
    if a["relaxed_breaks_correct"]:
        print(f"  WARNING relaxed fails a strictly-correct case: {a['relaxed_breaks_correct']}")
    before = compute_abstain_metrics(per_case, cases)
    after = compute_abstain_metrics(apply_relaxed(per_case, a["context_only"]), cases)
    print(
        f"  assumption_case_handling: {before['assumption_cases_handled']}/"
        f"{before['assumption_cases']} -> {after['assumption_cases_handled']}/"
        f"{after['assumption_cases']}  ({before['assumption_case_handling']:.1%} -> "
        f"{after['assumption_case_handling']:.1%})"
    )
    combined = combined_rule(per_case, cases, gold)
    final = compute_abstain_metrics(combined["records"], cases)
    print(
        f"  combined (year verifier + relaxed comparator; answer_must_state unscored, so an "
        f"upper bound): {final['assumption_cases_handled']}/{final['assumption_cases']} "
        f"({final['assumption_case_handling']:.1%}); credited {combined['credited']}"
    )
    for label, records in (
        ("strict comparator", per_case),
        ("relaxed comparator", apply_relaxed(per_case, a["context_only"])),
        ("combined", combined["records"]),
    ):
        o = assumption_outcomes(records, cases)
        print(
            f"    {label:<20} answered correctly {o['answered_correct']:>2}, "
            f"abstained {o['abstained']:>2}, answered wrong {o['answered_wrong']:>2} of {o['n']}"
        )
    fabricated = {f["id"] for f in year_audit(per_case, cases)["ungrounded"]}
    both = sorted(set(a["context_only"]) & fabricated)
    print(
        f"  of the {len(a['context_only'])} newly credited, {len(both)} state a year no result "
        f"cell contains: {both}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    args = ap.parse_args(argv)
    cases = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    gold = gold_results(cases, args.db)
    carriers = gold_context_cases(cases, gold)
    print(f"gold cases with a context column ({len(carriers)}): {carriers}")
    for path in args.reports:
        per_case = load_jsonl(path)
        _report(f"{path.name} (as measured)", per_case, cases, gold)
        _report(f"{path.name} (shipped)", revert_exec_error_repairs(per_case), cases, gold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
