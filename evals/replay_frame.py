# ruff: noqa: E501  (report table rows are single lines)
"""What does the answer framing (ledgerql/frame.py) state on the runs we already have?

The framing is a pure function of the question, the winning SQL and the database, and every Phase 5
record keeps its winning SQL, so it can be replayed on the 30B and 32B runs with no GPU. For each
answered record on a case with `answer_must_state` items this builds the frame and grades **the
frame text alone** against the items. That isolates the new component's contribution. The full
effect on an answer also depends on the writer no longer stating a period of its own, which only a
live run can show (`evals/run_eval.py`).

    python -m evals.replay_frame --write reports/frame_replay.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import must_state
from ledgerql import frame as frame_module

DEFAULT_DB = "data/ledgerql.duckdb"


def replay(
    records: list[dict], questions: dict[str, str], db_path: str, judge=None, items=None
) -> list[dict]:
    items = items if items is not None else must_state.load_patterns()
    out = []
    for r in records:
        if not r.get("answer") or not r.get("generated_sql") or r["id"] not in items:
            continue
        shape = frame_module.ResultShape(r.get("columns") or [], len(r.get("rows") or []))
        frame = frame_module.frame_answer(
            questions[r["id"]], r["generated_sql"], shape, db_path=db_path
        )
        graded = must_state.grade_case(
            items[r["id"]], frame.text or None, None, judge, questions[r["id"]]
        )
        out.append(
            {
                "id": r["id"],
                "expected": r["expected"],
                "assumed": frame.assumed,
                "frame": frame.text,
                "items": [
                    {"item": g.item, "passed": g.passed, "decided_by": g.decided_by} for g in graded
                ],
                "frame_stated": must_state.stated(graded) if frame.text else False,
            }
        )
    return out


def render(by_run: dict[str, list[dict]]) -> str:
    lines = [
        "# The answer framing, replayed on the Phase 5 runs",
        "",
        "For each answered record on a rubric case, the framing is rebuilt from its question, its "
        "recorded winning SQL and the database (`ledgerql/frame.py`, deterministic) and the **frame "
        "text alone** is graded against the case's `answer_must_state` items. It isolates what the "
        "new component states; whether the full answer then verifies depends on the writer no longer "
        "inventing a period, which only a live run shows.",
        "",
        "| run | case | state it would emit | frame states every item | frame |",
        "|---|---|---|---|---|",
    ]
    for run, rows in by_run.items():
        for r in rows:
            state = "ANSWER_WITH_ASSUMPTION" if r["assumed"] else "ANSWER"
            mark = {True: "yes", False: "**no**", None: "not gradable"}[r["frame_stated"]]
            lines.append(
                f"| {run} | {r['id']} | {state} | {mark} | {r['frame'][:140] or '(none)'} |"
            )
    lines += ["", "## Summary (assumption cases only)", ""]
    for run, rows in by_run.items():
        asm = [r for r in rows if r["expected"] == "ANSWER_WITH_ASSUMPTION"]
        stated = sum(r["frame_stated"] is True for r in asm)
        lines.append(
            f"- {run}: the frame states every rubric item on {stated} of {len(asm)} answered assumption cases"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--write", type=Path)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    args = ap.parse_args(argv)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    questions = {}
    for line in open(Path(__file__).resolve().parent / "gold.jsonl"):
        case = json.loads(line)
        questions[case["id"]] = case["question"]
    by_run = {}
    for name in ("qwen3_30b", "qwen25_32b"):
        path = args.reports_dir / f"eval_bridges2_{name}_measured.jsonl"
        records = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        by_run[name] = replay(records, questions, args.db, judge)
    text = render(by_run)
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
