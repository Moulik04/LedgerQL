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

from evals import measurement_pin, must_state, run_eval
from evals import rescore_v2 as R
from ledgerql import frame as frame_module
from ledgerql import refusal as refusal_module

DEFAULT_DB = "data/ledgerql.duckdb"


def load_run(run_dir: Path) -> list[dict]:
    files = sorted(Path(run_dir).glob("eval_*.jsonl"))
    if not files:
        raise FileNotFoundError(f"no eval_*.jsonl in {run_dir}")
    return [json.loads(x) for x in files[-1].read_text().splitlines() if x.strip()]


def ablate_frame(records: list[dict], questions: dict[str, str], db_path: str) -> list[dict]:
    """The same records with the framing text removed from each answer, to isolate what the framing
    contributes (the writer's own sentence is unchanged). The framing is a pure function of the
    question, the recorded winning SQL and the database, so it is recomputed exactly and cut."""
    out = []
    for rec in records:
        answer = rec.get("answer")
        if answer and rec.get("generated_sql"):
            shape = frame_module.ResultShape(rec.get("columns") or [], len(rec.get("rows") or []))
            text = frame_module.frame_answer(
                questions.get(rec["id"], ""), rec["generated_sql"], shape, db_path=db_path
            ).text
            if text and answer.endswith(text):
                rec = {**rec, "answer": answer[: -len(text)].rstrip()}
        out.append(rec)
    return out


def recompute_hallucination(records: list[dict], questions: dict[str, str], db_path: str) -> dict:
    """The hallucinated-number rate recomputed from recorded answers, verified exactly as the
    pipeline verified them (the framing's year and day labels as context). A run made before
    `run_eval` did this carries a flag that counts those labels as invented numbers."""
    answered, flagged = 0, []
    for rec in records:
        if not rec.get("answer"):
            continue
        answered += 1
        verdict = run_eval.verify_as_pipeline(
            rec["answer"],
            rec.get("columns") or [],
            [tuple(r) for r in (rec.get("rows") or [])],
            rec.get("generated_sql") or rec.get("sql"),
            questions.get(rec["id"], ""),
            db_path,
        )
        if not verdict.ok:
            flagged.append(rec["id"])
    return {
        "answered": answered,
        "flagged": flagged,
        "rate": len(flagged) / answered if answered else 0.0,
    }


ACCEPTANCE_IDS = ("M01", "M02", "M06", "M08", "U02", "U07")  # PHASE_5_5_MASTER_PROMPT.md Task 2


def rubric_rows(
    records: list[dict],
    questions: dict[str, str],
    db_path: str,
    judge=None,
    replay_refusal: bool = True,
) -> list[dict]:
    """One row per record on a case that has `answer_must_state` items, abstain-expected cases
    included: its tier and whether its text states every item (True, False, or None if it could not
    be graded). `replay_refusal=False` grades a run that predates abstain explanations as it was,
    with no refusal text to grade."""
    items = must_state.load_patterns()
    gold = R.load_gold("v3")
    rows = []
    for rec in records:
        if rec["id"] not in items:
            continue
        refusal = rec.get("refusal")
        if (
            refusal is None
            and replay_refusal
            and rec.get("answer") is None
            and rec.get("reason_code")
        ):
            refusal = refusal_module.explain(
                rec["reason_code"], questions[rec["id"]], db_path=db_path
            ).text
        graded = must_state.grade_case(
            items[rec["id"]], rec.get("answer"), refusal, judge, questions[rec["id"]]
        )
        rows.append(
            {
                "id": rec["id"],
                "tier": gold[rec["id"]]["tier"],
                "rubric_pass": must_state.stated(graded),
            }
        )
    return rows


def tier_rubric(rows: list[dict]) -> dict[str, dict[str, int]]:
    """Per tier, the records on rubric cases and how many state every rubric item. A record that
    could not be graded is not a pass."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        cell = out.setdefault(r["tier"], {"n": 0, "stated": 0})
        cell["n"] += 1
        cell["stated"] += r["rubric_pass"] is True
    return out


def acceptance(cases: list[dict], ids: tuple[str, ...] = ACCEPTANCE_IDS) -> dict[str, str]:
    """For each named case: "1.0" if its value is correct and its prose states its assumption;
    otherwise why not: abstained, right value but extra columns (strict fails, relaxed passes),
    wrong value, or assumption not stated."""
    by_id = {c["id"]: c for c in cases}
    out = {}
    for i in ids:
        c = by_id.get(i)
        if c is None:
            out[i] = "not run"
        elif c["state"] == "ABSTAIN":
            out[i] = "0 (abstained)"
        elif not c["correct_v3"] and c.get("correct_v3r"):
            out[i] = "0 (right value, extra columns: strict fails, relaxed passes)"
        elif not c["correct_v3"]:
            out[i] = "0 (wrong value)"
        elif c["stated"] is not True:
            out[i] = "0 (assumption not stated)"
        else:
            out[i] = "1.0"
    return out


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
                "correct_v3r": None if s is None else s.verdict["v3r"],
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
        "assumption_relaxed": R.assumption_split(scored)["v3r"],
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
        f"Under the relaxed comparator (extra columns ignored): answered correctly "
        f"{out['assumption_relaxed']['answered_correct']}, of which stated "
        f"{out['assumption_relaxed']['stated']}.",
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
    ap.add_argument(
        "--ablate-frame", action="store_true", help="grade the answers with the framing removed"
    )
    args = ap.parse_args(argv)
    measurement_pin.require_unchanged(args.db)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    records = load_run(args.run_dir)
    if args.ablate_frame:
        questions = {c["id"]: c["question"] for c in R.load_gold("v1").values()}
        records = ablate_frame(records, questions, args.db)
    text = render(summarize(records, args.db, judge))
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
