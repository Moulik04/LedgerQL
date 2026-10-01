"""Re-grade the refusal rubric items on existing runs, offline.

An abstain's explanation (`ledgerql/refusal.py`) is a pure function of the reason code, the
question and the database, so it can be replayed on every recorded abstain without a model run:
for each abstaining record on a case with `answer_must_state` items, build the refusal sentence
and grade it with `evals/must_state.py`. This is what makes the six abstain-case rubric items and
the "state the reason" half of R07 and H06 gradable on the existing Phase 5 runs.

    python -m evals.replay_refusals                  # both measured runs
    python -m evals.replay_refusals --write reports/refusal_replay.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import must_state
from ledgerql import refusal

DEFAULT_DB = "data/ledgerql.duckdb"


def replay(
    records: list[dict], questions: dict[str, str], db_path: str, judge=None, items=None
) -> list[dict]:
    """One row per abstaining rubric-case record: its refusal sentence and its items' grades."""
    items = items if items is not None else must_state.load_patterns()
    out = []
    for r in records:
        if r.get("answer") is not None or not r.get("reason_code") or r["id"] not in items:
            continue
        # Only cases with an item about the refusal: an assumption case's "which fiscal year"
        # item is about an answer, and an abstain has none to state.
        if not any(i["surface"] in ("refusal", "either") for i in items[r["id"]]):
            continue
        question = questions[r["id"]]
        text = refusal.explain(r["reason_code"], question, db_path=db_path).text
        graded = must_state.grade_case(items[r["id"]], None, text, judge, question)
        out.append(
            {
                "id": r["id"],
                "reason_code": r["reason_code"],
                "refusal": text,
                "items": [
                    {"item": g.item, "passed": g.passed, "decided_by": g.decided_by,
                     "pattern": g.pattern_pass, "judge": g.judge_pass}
                    for g in graded
                ],  # fmt: skip
                "stated": must_state.stated(graded),
            }
        )
    return out


def render(by_run: dict[str, list[dict]], items: dict) -> str:
    lines = [
        "# Refusal rubric items, replayed deterministically",
        "",
        "Each abstain's explanation is rebuilt from its reason code, the question and the database "
        "(`ledgerql/refusal.py`: templates and a documented-gaps registry, no model) and graded "
        "against the case's rubric items (`evals/must_state.py`). Not a model run: the text is a "
        "pure function of the recorded abstain.",
        "",
        "| run | case | reason | refusal states the item(s) | refusal text |",
        "|---|---|---|---|---|",
    ]
    for run, rows in by_run.items():
        for r in rows:
            mark = {True: "yes", False: "**no**", None: "not gradable"}[r["stated"]]
            lines.append(
                f"| {run} | {r['id']} | {r['reason_code']} | {mark} | {r['refusal'][:150]} |"
            )
    lines += [
        "",
        "Rubric cases that abstained in no run listed above were answered by the model instead.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--write", type=Path)
    ap.add_argument(
        "--judge", action="store_true", help="the local judge decides judge-primary items"
    )
    ap.add_argument("--judge-model", default="llama3.1:8b")
    args = ap.parse_args(argv)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    questions = {}
    for line in open(Path(__file__).resolve().parent / "gold.jsonl"):
        case = json.loads(line)
        questions[case["id"]] = case["question"]
    items = must_state.load_patterns()
    by_run = {}
    for name in ("qwen3_30b", "qwen25_32b"):
        path = args.reports_dir / f"eval_bridges2_{name}_measured.jsonl"
        records = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        by_run[name] = replay(records, questions, args.db, judge, items=items)
    text = render(by_run, items)
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
