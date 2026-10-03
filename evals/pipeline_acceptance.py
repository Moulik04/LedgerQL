# ruff: noqa: E501  (report format strings are single lines)
"""Task 2/3 acceptance from a pipeline run directory, under the frozen gold v3 (strict).

For each run it reports: integrity (records, infrastructure failures); the states emitted and the
3x3 expected-by-observed matrix; execution accuracy; the assumption cases answered correctly *with
the assumption stated* (the acceptance metric), with and without the framing; the hallucinated-number
rate recomputed as the pipeline verified it; the confidently-wrong rate, coverage; the six named
Task 2 cases; and the per-tier rubric rate against a baseline run made before the framing existed.
A run with infrastructure failures is reported on its usable records only, and says so.

    python -m evals.pipeline_acceptance reports/runs/<30b> reports/runs/<32b> --judge --write out.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evals import must_state, run_eval, summarize_run
from evals import rescore_v2 as R

STATES = ("ANSWER", "ANSWER_WITH_ASSUMPTION", "ABSTAIN")
TIERS = ("unit_period", "ambiguous", "schema_bait")
DEFAULT_DB = "data/ledgerql.duckdb"


def split_usable(records: list[dict]) -> tuple[list[dict], list[str]]:
    dropped = run_eval.infra_error_ids(records)
    return [r for r in records if r["id"] not in set(dropped)], dropped


def confusion(cases: list[dict]) -> dict[str, dict[str, int]]:
    m = {e: dict.fromkeys(STATES, 0) for e in STATES}
    for c in cases:
        m[c["expected"]][c["state"]] += 1
    return m


def headline(cases: list[dict]) -> dict:
    answered = [c for c in cases if c["state"] != "ABSTAIN"]
    wrong = [c for c in answered if c["correct_v3"] is False or (c["expected"] == "ABSTAIN")]
    answerable = [c for c in cases if c["expected"] in ("ANSWER", "ANSWER_WITH_ASSUMPTION")]
    return {
        "confidently_wrong": {"wrong": len(wrong), "answered": len(answered)},
        "coverage": {
            "answered": sum(c["state"] != "ABSTAIN" for c in answerable),
            "answerable": len(answerable),
        },
    }


def _questions() -> dict[str, str]:
    return {c["id"]: c["question"] for c in R.load_gold("v1").values()}


def analyse(run_dir: Path, baseline: list[dict], db: str, judge=None, label: str = "") -> dict:
    questions = _questions()
    records_all = summarize_run.load_run(run_dir)
    records, dropped = split_usable(records_all)
    summary = summarize_run.summarize(records, db, judge)
    ablated = summarize_run.summarize(summarize_run.ablate_frame(records, questions, db), db, judge)
    usable_ids = {r["id"] for r in records}
    base_usable = [r for r in baseline if r["id"] in usable_ids]
    new_rows = summarize_run.rubric_rows(records, questions, db, judge)
    old_rows = summarize_run.rubric_rows(base_usable, questions, db, judge, replay_refusal=False)
    return {
        "label": label,
        "records": len(records_all),
        "dropped": dropped,
        "usable": len(records),
        "summary": summary,
        "ablated": ablated,
        "hallucination": summarize_run.recompute_hallucination(records, questions, db),
        "confusion": confusion(summary["cases"]),
        "headline": headline(summary["cases"]),
        "acceptance": summarize_run.acceptance(summary["cases"]),
        "tiers_new": summarize_run.tier_rubric(new_rows),
        "tiers_old": summarize_run.tier_rubric(old_rows),
    }


def render(analyses: list[dict]) -> str:
    lines = ["# Task 2/3 acceptance from the pipeline runs (gold v3, strict)", ""]
    for a in analyses:
        sp, ab = a["summary"]["assumption"], a["ablated"]["assumption"]
        lines += [f"## {a['label']}", ""]
        status = (
            "complete"
            if not a["dropped"]
            else (
                f"**PARTIAL: {len(a['dropped'])} of {a['records']} records failed for infrastructure "
                f"reasons and are excluded: {a['dropped']}**"
            )
        )
        lines += [
            f"Integrity: {a['records']} records, {status}. Figures cover {a['usable']} records.",
            "",
        ]
        lines += [f"States emitted: {a['summary']['states']}.", ""]
        lines += ["| expected \\ observed | " + " | ".join(STATES) + " |", "|---|---|---|---|"]
        for e in STATES:
            lines.append(f"| {e} | " + " | ".join(str(a["confusion"][e][o]) for o in STATES) + " |")
        n_a = a["summary"]["answer_accuracy"]
        h = a["headline"]
        hal = a["hallucination"]
        lines += [
            "",
            f"Execution accuracy on the `ANSWER` cases that ran: {n_a['v3']}/{n_a['n']} (strict v3), "
            f"{n_a['v3r']}/{n_a['n']} relaxed.",
            f"Hallucinated-number rate including years, verified as the pipeline verified it: "
            f"**{hal['rate']:.1%}** ({len(hal['flagged'])} of {hal['answered']} answered; {hal['flagged']}).",
            f"Confidently wrong: {h['confidently_wrong']['wrong']} of {h['confidently_wrong']['answered']} "
            f"answered. Coverage: {h['coverage']['answered']} of {h['coverage']['answerable']} answerable.",
            "",
            f"**Assumption cases ({sp['n']} that ran): answered correctly with the assumption stated: "
            f"{sp['stated']}** (baseline 0 of 19). Answered correctly {sp['answered_correct']}, of which "
            f"not stated {sp['not_stated']}, no rubric items {sp['unassessed']}; abstained {sp['abstained']} "
            f"(reason stated {sp['abstained_reason_stated']}); answered wrong {sp['answered_wrong']}.",
            f"Ablation (framing text removed, same records): stated {ab['stated']}.",
            "",
            "Task 2's six named cases (score 1.0 = correct value and the assumption stated): "
            + ", ".join(f"{k} {v}" for k, v in a["acceptance"].items())
            + ".",
            "",
            "Rubric pass rate by tier (records on rubric cases that state every item; not gradable counts as not stated), baseline run vs this run, same cases:",
            "",
            "| tier | baseline | this run |",
            "|---|---|---|",
        ]
        for t in TIERS:
            o, n = a["tiers_old"].get(t, {"n": 0, "stated": 0}), a["tiers_new"].get(
                t, {"n": 0, "stated": 0}
            )
            lines.append(f"| {t} | {o['stated']}/{o['n']} | {n['stated']}/{n['n']} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", metavar="label=dir")
    ap.add_argument("--baselines", nargs="+", metavar="label=file", required=True,
                    help="the earlier measured report for each run, in the same order")  # fmt: skip
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    out = []
    for spec, base in zip(args.runs, args.baselines, strict=True):
        label, _, directory = spec.partition("=")
        _, _, base_file = base.partition("=")
        baseline = R._configs(R.load_report(Path(base_file)))["shipped + year rule"]
        out.append(analyse(Path(directory), baseline, args.db, judge, label))
    text = render(out)
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
