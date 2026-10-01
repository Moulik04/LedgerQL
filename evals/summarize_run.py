# ruff: noqa: E501  (report format strings are single lines)
"""Summarise a `run_eval` run directory under the frozen gold v3: each case's observed state,
whether its value is correct (strict v3), whether its prose states the case's rubric items, and the
assumption-case split (answered correctly with the assumption stated, abstained, answered wrong).

    python -m evals.summarize_run reports/runs/<dir> [--judge] [--write out.md]

Used for the local 7B runs and for Bridges-2 pipeline runs once retrieved. Grading is offline: the
rubric is recomputed from the recorded answer and refusal text, so a judge can be applied after the
fact (`--judge`), which matters on a machine that cannot hold the pipeline model and a judge at once.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals import must_state
from evals import rescore_v2 as R

DEFAULT_DB = "data/ledgerql.duckdb"


def load_run(run_dir: Path) -> list[dict]:
    files = sorted(Path(run_dir).glob("eval_*.jsonl"))
    if not files:
        raise FileNotFoundError(f"no eval_*.jsonl in {run_dir}")
    return [json.loads(x) for x in files[-1].read_text().splitlines() if x.strip()]


def summarize(records: list[dict], db_path: str = DEFAULT_DB, judge=None) -> dict:
    gold = R.Gold(db_path)
    scores = {s.id: s for s in R.score_report(records, gold, judge)}
    cases = []
    for rec in records:
        s = scores.get(rec["id"])
        cases.append(
            {
                "id": rec["id"],
                "expected": rec["expected"],
                "state": rec.get("state") or ("ABSTAIN" if rec.get("answer") is None else "ANSWER"),
                "reason_code": rec.get("reason_code"),
                "correct_v3": None if s is None else s.verdict["v3"],
                "stated": None if s is None else s.rubric_pass,
                "answer": rec.get("answer"),
                "refusal": rec.get("refusal"),
            }
        )
    scored = list(scores.values())
    return {
        "cases": cases,
        "states": dict(Counter(c["state"] for c in cases)),
        "assumption": R.assumption_split(scored)["v3"],
        "answer_accuracy": R.accuracy(scored, "ANSWER"),
    }


def render(out: dict) -> str:
    sp = out["assumption"]
    lines = [
        "# Run summary (gold v3, strict)",
        "",
        f"States emitted: {out['states']}.",
        "",
        f"Assumption cases ({sp['n']}): answered correctly **{sp['answered_correct']}**, of which the "
        f"assumption is **stated {sp['stated']}** (not stated {sp['not_stated']}, no rubric or not "
        f"gradable {sp['unassessed']}); abstained {sp['abstained']} (reason stated "
        f"{sp['abstained_reason_stated']}); answered wrong {sp['answered_wrong']}.",
        "",
        "| case | expected | state | reason | correct (v3) | prose states items | text |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in out["cases"]:
        text = (c["answer"] or c["refusal"] or "").replace("\n", " ")[:150]
        lines.append(
            f"| {c['id']} | {c['expected']} | {c['state']} | {c['reason_code'] or ''} | "
            f"{c['correct_v3']} | {c['stated']} | {text} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    text = render(summarize(load_run(args.run_dir), args.db, judge))
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
