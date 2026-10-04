# ruff: noqa: E501  (markdown report lines)
"""Replay a pipeline run's drafts under two versions of the verifier, no model needed.

    python -m evals.replay_verifier reports/runs/<run>/eval_<date>.jsonl --old-rev 3c235d1 \\
        [--new-rev <commit>] [--write reports/verifier_replay_<run>.md]

Without `--new-rev` the second verifier is the one in the working tree; with it, both sides are
committed revisions and the report reads the same whatever the working tree holds.

The verifier runs after the answer is drafted, so a change to it cannot change a draft: only
which drafts ship. A run made since blocked drafts were stored (2026-10-03, configuration H2) holds
every draft's text, shipped (`answer`) or blocked (`blocked_draft`), so the older verifier can be
replayed on exactly the same texts. That isolates the verifier change from run-to-run sampling
noise, which a second model run could not do.

For each version: the draft rate (blocked over drafted), and what the independent auditor
(`evals/number_audit.py`) says of each side. A blocked draft the auditor grounds completely is a
false abstain; a shipped answer the auditor flags is an invented number the verifier let through.
A draft with no ungrounded claim but one the auditor cannot resolve is counted as neither.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

from evals import number_audit, pipeline_acceptance, run_eval
from evals.passn_scoring import load_jsonl
from ledgerql import verify as current_verify

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = "data/ledgerql.duckdb"


def load_verifier(rev: str):
    """`ledgerql/verify.py` as it was at git revision `rev`, as a module of its own."""
    source = subprocess.run(
        ["git", "show", f"{rev}:ledgerql/verify.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    name = f"verify_at_{rev}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}.py"
        path.write_text(source)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def verifiers(old_rev: str, new_rev: str | None) -> dict:
    """The two verifiers to replay, by the name the report gives each."""
    new = (
        {f"verifier at {new_rev}": load_verifier(new_rev).verify}
        if new_rev
        else {"verifier now": current_verify.verify}
    )
    return {f"verifier at {old_rev}": load_verifier(old_rev).verify, **new}


def replay(records: list[dict], verifiers: dict, questions: dict[str, str], db: str | None):
    """One row per drafted record: the draft, each verifier's verdict on it, and the auditor's
    claims by tier. Returns (rows, ids of blocked records whose draft was not stored)."""
    rows, not_stored = [], []
    for rec in records:
        text = rec.get("answer") or rec.get("blocked_draft")
        if not text:
            if rec.get("reason_code") == "UNGROUNDED_ANSWER":
                not_stored.append(rec["id"])
            continue
        result = [tuple(r) for r in rec["rows"]]
        sql = rec.get("generated_sql")
        audit = number_audit.audit_answer(text, rec["columns"], result, sql, db)
        row = {
            "id": rec["id"],
            "text": text,
            "ungrounded": [(c.kind, c.text) for c in audit.ungrounded],
            "unresolved": [(c.kind, c.text) for c in audit.unresolved],
            "weak": [(c.kind, c.text) for c in audit.of("weak")],
            "derived": [(c.kind, c.text) for c in audit.of("derived")],
            "verdicts": {},
        }
        for name, verifier in verifiers.items():
            v = run_eval.verify_as_pipeline(
                text, rec["columns"], result, sql, questions.get(rec["id"], ""), db, verifier
            )
            row["verdicts"][name] = {"ok": v.ok, "detail": v.detail}
        rows.append(row)
    return rows, not_stored


def _verdict(row: dict) -> str:
    """The auditor on a blocked draft. An unresolved claim is no verdict: with nothing ungrounded
    beside it, the block is neither an invention nor a false abstain."""
    if row["ungrounded"]:
        return "invented"
    return "unresolved" if row["unresolved"] else "false abstain"


def summarize(rows: list[dict], name: str) -> dict[str, int]:
    blocked = [r for r in rows if not r["verdicts"][name]["ok"]]
    shipped = [r for r in rows if r["verdicts"][name]["ok"]]
    return {
        "drafted": len(rows),
        "blocked": len(blocked),
        "blocked_invented": sum(bool(r["ungrounded"]) for r in blocked),
        "blocked_unresolved": sum(_verdict(r) == "unresolved" for r in blocked),
        "false_abstains": sum(_verdict(r) == "false abstain" for r in blocked),
        "shipped": len(shipped),
        "shipped_flagged": sum(bool(r["ungrounded"]) for r in shipped),
        "shipped_unresolved": sum(bool(r["unresolved"]) for r in shipped),
        "shipped_weak": sum(bool(r["weak"]) for r in shipped),
        "shipped_derived": sum(bool(r["derived"]) for r in shipped),
    }


def changed(rows: list[dict], a: str, b: str) -> list[dict]:
    return [r for r in rows if r["verdicts"][a]["ok"] != r["verdicts"][b]["ok"]]


def _rate(n: int, d: int) -> str:
    return f"{n} of {d} ({n / d:.1%})" if d else "0 of 0"


def render(rows: list[dict], not_stored: list[str], old: str, new: str, source: str) -> str:
    o, n = summarize(rows, old), summarize(rows, new)
    lines = [
        f"# Two versions of the verifier, replayed on the same drafts ({source})",
        "",
        f"`{old}` and `{new}` are two versions of `ledgerql/verify.py`, replayed on the drafts this run",
        "stored. The drafts are identical on both sides (the verifier runs after the answer is written),",
        "so every difference below is the verifier's. The auditor is `evals/number_audit.py`.",
        "",
        f"| | {old} | {new} |",
        "|---|---|---|",
        f"| drafted, with the draft's text stored | {o['drafted']} | {n['drafted']} |",
        f"| **draft rate** (blocked / drafted) | {_rate(o['blocked'], o['drafted'])} | {_rate(n['blocked'], n['drafted'])} |",
        f"| blocked, and the auditor also finds an invented number | {o['blocked_invented']} | {n['blocked_invented']} |",
        f"| **false abstains** (blocked, but the auditor grounds every claim) | {o['false_abstains']} | {n['false_abstains']} |",
        f"| blocked, nothing ungrounded, but a claim the auditor cannot resolve (counted as neither) | {o['blocked_unresolved']} | {n['blocked_unresolved']} |",
        f"| shipped | {o['shipped']} | {n['shipped']} |",
        f"| **shipped, and the auditor flags an invented number** | {o['shipped_flagged']} | {n['shipped_flagged']} |",
        f"| shipped with an unresolved claim (reported, not counted) | {o['shipped_unresolved']} | {n['shipped_unresolved']} |",
        f"| shipped with a weak claim (reported, not counted) | {o['shipped_weak']} | {n['shipped_weak']} |",
        f"| shipped with a derived claim | {o['shipped_derived']} | {n['shipped_derived']} |",
        "",
    ]
    if not_stored:
        lines += [f"Blocked with no stored draft, so not replayed: {not_stored}.", ""]
    diff = changed(rows, old, new)
    lines += [f"## Drafts whose verdict changed: {len(diff)}", ""]
    for r in diff:
        was, now = r["verdicts"][old], r["verdicts"][new]
        lines += [
            f"### {r['id']}: {'shipped' if was['ok'] else 'blocked'} -> {'shipped' if now['ok'] else 'blocked'}",
            "",
            f"- draft: {r['text']}",
            f"- {old}: {was['detail'] or 'accepted'}",
            f"- {new}: {now['detail'] or 'accepted'}",
            f"- auditor: ungrounded {r['ungrounded']}; unresolved {r['unresolved']}; weak {r['weak']}; derived {r['derived']}",
            "",
        ]
    still = [r for r in rows if not r["verdicts"][new]["ok"] and r not in diff]
    lines += [f"## Drafts blocked by both: {len(still)}", ""]
    for r in still:
        lines += [
            f"### {r['id']}: {_verdict(r)}",
            "",
            f"- draft: {r['text']}",
            f"- {new}: {r['verdicts'][new]['detail']}",
            f"- auditor: ungrounded {r['ungrounded']}; unresolved {r['unresolved']}; weak {r['weak']}; derived {r['derived']}",
            "",
        ]
    open_ = [r for r in rows if r["verdicts"][new]["ok"] and r["unresolved"]]
    lines += [f"## Shipped with an unresolved claim: {len(open_)}", ""]
    for r in open_:
        lines += [f"### {r['id']}", "", f"- answer: {r['text']}", f"- unresolved: {r['unresolved']}", ""]  # fmt: skip
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path, help="a run_eval per-case jsonl made with stored drafts")
    ap.add_argument("--old-rev", required=True, help="git revision of the verifier to replay")
    ap.add_argument("--new-rev", help="git revision of the second verifier (default: working tree)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    both = verifiers(args.old_rev, args.new_rev)
    old, new = both
    rows, not_stored = replay(
        load_jsonl(args.report), both, pipeline_acceptance._questions(), args.db
    )
    text = render(rows, not_stored, old, new, args.report.name)
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
