# ruff: noqa: E501  (markdown report lines)
"""The independent number audit beside the pipeline's verifier, on dev runs only.

    python -m evals.audit_vs_verify [--write reports/number_audit_vs_verify.md]

For every answered record of the committed dev pipeline runs, the verifier's verdict (exactly as the
pipeline gave it: `run_eval.verify_as_pipeline`) and the auditor's (`evals/number_audit.py`). A
shipped answer has passed the verifier, so every disagreement here is the auditor flagging
something the verifier let through; each is printed with its claims, to be judged by reading which
side is right. A claim the auditor cannot resolve (a year or date some company has, under SQL whose
company it cannot tell) is its own status: listed, and counted on neither side. Then the same two
on planted invented values in every form, which is where the verifier's blind spots show without
waiting for a model to produce them.

This module is the only place the auditor and the verifier meet; `number_audit.py` imports neither.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import number_audit, pipeline_acceptance, run_eval
from ledgerql import verify

RUNS = {
    "30B rerun 47367323": "reports/eval_bridges2_qwen3_30b_pipeline_47367323.jsonl",
    "30B partial 47314853": "reports/eval_bridges2_qwen3_30b_pipeline_47314853_PARTIAL.jsonl",
    "32B 47314855": "reports/eval_bridges2_qwen25_32b_pipeline_47314855.jsonl",
}
DEFAULT_DB = "data/ledgerql.duckdb"

PLANT_COLUMNS = ["ticker", "fiscal_year", "value"]
PLANT_ROWS = [("AAPL", 2025, 416161000000.0)]
PLANT_SQL = (
    "SELECT ticker, fiscal_year, value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2025"
)
# (form, an invented value in that form). The true value is 416,161,000,000 in fiscal 2025.
PLANTS = [
    ("digits", "Revenue was 417,500,000,000.0."),
    ("decimal", "Revenue was 417500000000.5."),
    ("magnitude word", "Revenue was $417.5 billion."),
    ("mis-scaled word", "Revenue was 416.161 million."),
    ("abbreviation B", "Revenue was $417.5B."),
    ("abbreviation bn", "Revenue was 417.5 bn."),
    ("abbreviation T", "Revenue was 0.45T."),
    ("abbreviation K", "Revenue was 417500K."),
    ("percent sign", "Growth was 38%."),
    ("percent word", "Growth was 38 percent."),
    ("spelled-out integer", "There were forty-two."),
    ("spelled-out scale", "Revenue was four hundred seventeen billion."),
    ("spelled-out decimal", "Growth was two point five percent."),
    ("small digit count", "There were 7 filings."),
    ("year, wrong", "For fiscal year 2022."),
    ("year, FY form", "For FY22."),
    ("date, long", "The period ended June 30, 2022."),
    ("date, ISO", "The period ended 2022-06-30."),
    ("date, US numeric", "The period ended 6/30/2022."),
    ("quarter label", "In the quarter Q2."),
    ("form code lookalike", "Filed a 391-K."),
    ("round number, no hedge", "Revenue was 420 billion."),
]


# Correct restatements of the same fact: the right verdict is to accept every one.
HONEST = [
    ("exact digits", "Revenue was 416,161,000,000.0."),
    ("magnitude word, exact", "Revenue was $416.161 billion."),
    ("rounded to the billion", "Revenue was about 416 billion."),
    ("rounded to a tenth of a billion", "Revenue was 416.2 billion."),
    ("rounded to ten billion", "Revenue was roughly 420 billion."),
    ("abbreviation B", "Revenue was $416B."),
    ("abbreviation bn", "Revenue was 416 bn."),
    ("abbreviation T", "Revenue was $0.4T."),
    ("in millions", "Revenue was 416,161 million."),
    ("spelled out", "Revenue was four hundred sixteen billion."),
    ("fiscal year, long", "For fiscal year 2025."),
    ("fiscal year, FY form", "For FY25."),
    ("form code", "Per the 10-K for fiscal 2025."),
    ("ordinal", "The 3rd largest filer."),
]


def load(path: str) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def blocks_by_run(db: str, runs: dict[str, str] | None = None) -> dict[str, dict]:
    """Per run: figure 1a's counts (`draft_rate`) and each blocked draft's verdict."""
    out = {}
    for label, path in (runs or RUNS).items():
        records = load(path)
        out[label] = {"rate": draft_rate(records, db), "blocks": classify_blocks(records, db)}
    return out


def compare_runs(db: str, runs: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    questions = pipeline_acceptance._questions()
    rows_out, totals = [], {}
    for label, path in (runs or RUNS).items():
        answered = 0
        for rec in load(path):
            if not rec.get("answer"):
                continue
            answered += 1
            result = [tuple(r) for r in rec["rows"]]
            sql = rec.get("generated_sql")
            v = run_eval.verify_as_pipeline(
                rec["answer"], rec["columns"], result, sql, questions.get(rec["id"], ""), db
            )
            a = number_audit.audit_answer(rec["answer"], rec["columns"], result, sql, db)
            rows_out.append(
                {
                    "run": label,
                    "id": rec["id"],
                    "answer": rec["answer"],
                    "columns": rec["columns"],
                    "rows": rec["rows"][:3],
                    "sql": sql,
                    "verifier_ok": v.ok,
                    "audit_clean": a.clean,
                    "ungrounded": [(c.kind, c.text) for c in a.ungrounded],
                    "unresolved": [(c.kind, c.text) for c in a.unresolved],
                    "weak": [(c.kind, c.text) for c in a.of("weak")],
                    "derived": [(c.kind, c.text) for c in a.of("derived")],
                    "claims": len(a.claims),
                }
            )
        totals[label] = answered
    return rows_out, totals


BLOCKED = "UNGROUNDED_ANSWER"


def classify_blocks(records: list[dict], db: str | None) -> list[dict]:
    """Every draft the verifier blocked, judged by the auditor on the stored draft text
    (`blocked_draft`, recorded since 2026-10-03). `invented`: the auditor finds an ungrounded claim
    too, so the block was right. `verifier false positive`: the auditor grounds every claim, so the
    verifier refused a true statement. `unresolved`: no claim is ungrounded but the auditor cannot
    resolve at least one, so it gives no verdict and the block counts on neither side. A weak or
    derived claim is listed and never makes a draft invented (protocol 6a). A record from before
    drafts were stored is `draft not stored`."""
    out = []
    for rec in records:
        if rec.get("reason_code") != BLOCKED:
            continue
        block = {"id": rec["id"], "draft": rec.get("blocked_draft"), "ungrounded": [],
                 "unresolved": [], "weak": [], "derived": [],
                 "refused": rec.get("blocked_claims", [])}  # fmt: skip
        if not block["draft"]:
            out.append({**block, "verdict": "draft not stored"})
            continue
        a = number_audit.audit_answer(
            block["draft"],
            rec["columns"],
            [tuple(r) for r in rec["rows"]],
            rec.get("generated_sql"),
            db,
        )
        block["ungrounded"] = [(c.kind, c.text) for c in a.ungrounded]
        block["unresolved"] = [(c.kind, c.text) for c in a.unresolved]
        block["weak"] = [(c.kind, c.text) for c in a.of("weak")]
        block["derived"] = [(c.kind, c.text) for c in a.of("derived")]
        verdict = (
            "invented"
            if block["ungrounded"]
            else "unresolved" if block["unresolved"] else "verifier false positive"
        )
        out.append({**block, "verdict": verdict})
    return out


def draft_rate(records: list[dict], db: str | None) -> dict[str, int]:
    """Figure 1a and what it is made of: of the answers the pipeline drafted (shipped plus
    blocked), how many the verifier blocked, split by the auditor's verdict on each block."""
    blocks = classify_blocks(records, db)
    shipped = sum(1 for r in records if r.get("answer"))
    count = {v: sum(b["verdict"] == v for b in blocks) for v in
             ("invented", "verifier false positive", "unresolved", "draft not stored")}  # fmt: skip
    return {
        "drafted": shipped + len(blocks),
        "shipped": shipped,
        "blocked": len(blocks),
        "invented": count["invented"],
        "verifier_false_positive": count["verifier false positive"],
        "unresolved": count["unresolved"],
        "draft_not_stored": count["draft not stored"],
    }


def plant_table() -> list[dict]:
    out = []
    for form, text in PLANTS:
        v = verify.verify(text, PLANT_COLUMNS, PLANT_ROWS, sql=PLANT_SQL)
        a = number_audit.audit_answer(text, PLANT_COLUMNS, PLANT_ROWS, PLANT_SQL)
        out.append({"form": form, "text": text, "verifier_catches": not v.ok,
                    "audit_catches": not a.clean})  # fmt: skip
    return out


def honest_table() -> list[dict]:
    out = []
    for form, text in HONEST:
        v = verify.verify(text, PLANT_COLUMNS, PLANT_ROWS, sql=PLANT_SQL)
        a = number_audit.audit_answer(text, PLANT_COLUMNS, PLANT_ROWS, PLANT_SQL)
        out.append({"form": form, "text": text, "verifier_accepts": v.ok, "audit_accepts": a.clean})
    return out


def render_blocks(by_run: dict[str, dict]) -> list[str]:
    lines = [
        "## Blocked drafts (figure 1a): an invented number, or the verifier being wrong?",
        "",
        "Of the answers the pipeline drafted (shipped plus blocked), the ones the verifier blocked, each",
        "judged by the auditor on the stored draft. A block the auditor also flags is an invented number;",
        "a block the auditor grounds completely is a verifier false positive. A block with no ungrounded",
        "claim but one the auditor cannot resolve is unresolved: counted on neither side. Runs from before",
        "2026-10-03 did not store the draft, so their blocks cannot be judged.",
        "",
        "| run | drafted | blocked | invented | verifier false positive | unresolved | draft not stored |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, b in by_run.items():
        r = b["rate"]
        lines.append(
            f"| {label} | {r['drafted']} | {r['blocked']} | {r['invented']} | "
            f"{r['verifier_false_positive']} | {r['unresolved']} | {r['draft_not_stored']} |"
        )
    lines.append("")
    for label, b in by_run.items():
        for blk in b["blocks"]:
            if blk["verdict"] == "draft not stored":
                continue
            lines += [
                f"### {label} / {blk['id']}: {blk['verdict']}",
                "",
                f"- draft: {blk['draft']}",
                f"- the verifier refused: {blk['refused']}",
                f"- auditor ungrounded: {blk['ungrounded']}; unresolved: {blk['unresolved']}; weak: {blk['weak']}; derived: {blk['derived']}",
                "",
            ]
    return lines


def render_unresolved(rows: list[dict]) -> list[str]:
    """Shipped answers with a claim the auditor cannot resolve, each to be judged by reading."""
    open_ = [r for r in rows if r["unresolved"]]
    lines = [
        f"## Unresolved claims in shipped answers: {len(open_)}",
        "",
        "A year or date some company in the database has, under SQL that restricts the company in a way",
        "the auditor cannot resolve (a pattern, a range, a negation, a subquery that names none). It can",
        "neither be tied to the answer nor ruled out: reported here, never counted as ungrounded.",
        "",
    ]
    for r in open_:
        lines += [
            f"### {r['run']} / {r['id']}",
            "",
            f"- answer: {r['answer']}",
            f"- sql: {r['sql']}",
            f"- unresolved: {r['unresolved']}",
            "",
        ]
    return lines


def render(
    rows: list[dict],
    totals: dict,
    plants: list[dict],
    honest: list[dict],
    blocks: dict[str, dict] | None = None,
) -> str:
    dis = [r for r in rows if r["verifier_ok"] != r["audit_clean"]]
    lines = [
        "# Independent number audit beside the verifier (dev runs only)",
        "",
        "`evals/number_audit.py` (spec: `evals/NUMBER_AUDIT_SPEC.md`) against `ledgerql/verify.py`, on every",
        "answered record of the committed dev pipeline runs. A shipped answer has passed the verifier, so",
        "every disagreement is the auditor flagging something the verifier let through.",
        "",
        "| run | answered | auditor flags | unresolved | weak | derived |",
        "|---|---|---|---|---|---|",
    ]
    for label, n in totals.items():
        rs = [r for r in rows if r["run"] == label]
        lines.append(
            f"| {label} | {n} | {sum(not r['audit_clean'] for r in rs)} | "
            f"{sum(bool(r['unresolved']) for r in rs)} | "
            f"{sum(bool(r['weak']) for r in rs)} | {sum(bool(r['derived']) for r in rs)} |"
        )
    lines += ["", f"Disagreements: {len(dis)} of {len(rows)} answered records.", ""]
    for r in dis:
        lines += [
            f"### {r['run']} / {r['id']}",
            "",
            f"- answer: {r['answer']}",
            f"- result: columns {r['columns']}, first rows {r['rows']}",
            f"- verifier: ok. auditor ungrounded: {r['ungrounded']}",
            "",
        ]
    lines += render_unresolved(rows)
    if blocks:
        lines += render_blocks(blocks)
    lines += [
        "## Planted invented values, both implementations",
        "",
        "The true value is 416,161,000,000 (fiscal 2025, AAPL). Each text states something invented.",
        "",
        "| form | text | verifier catches | auditor catches | verdict |",
        "|---|---|---|---|---|",
    ]
    for p in plants:
        verdict = (
            "agree"
            if p["verifier_catches"] and p["audit_catches"]
            else "verifier blind spot" if p["audit_catches"] else "auditor blind spot"
        )
        lines.append(
            f"| {p['form']} | {p['text']} | {'yes' if p['verifier_catches'] else '**no**'} | "
            f"{'yes' if p['audit_catches'] else '**no**'} | {verdict} |"
        )
    lines += [
        "",
        "## Correct restatements of the same fact, both implementations",
        "",
        "Every row is true, so the right verdict is to accept.",
        "",
        "| form | text | verifier accepts | auditor accepts | verdict |",
        "|---|---|---|---|---|",
    ]
    for h in honest:
        verdict = (
            "agree"
            if h["verifier_accepts"] and h["audit_accepts"]
            else "verifier too strict" if h["audit_accepts"] else "auditor too strict"
        )
        lines.append(
            f"| {h['form']} | {h['text']} | {'yes' if h['verifier_accepts'] else '**no**'} | "
            f"{'yes' if h['audit_accepts'] else '**no**'} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--write", type=Path)
    ap.add_argument(
        "--run",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="a per-case jsonl to audit instead of the committed dev runs (repeatable)",
    )
    args = ap.parse_args(argv)
    runs = dict(r.split("=", 1) for r in args.run) or None
    rows, totals = compare_runs(args.db, runs)
    text = render(rows, totals, plant_table(), honest_table(), blocks_by_run(args.db, runs))
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
