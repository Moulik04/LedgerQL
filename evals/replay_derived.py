"""Replay committed per-case reports through hypothetical pipeline changes.

This is where every *derived* figure in DECISIONS.md and the Task 6b spec comes
from, and it exists so anyone can regenerate them. It was first a throwaway
script in a scratch directory; that directory did not survive a reboot and the
spec's section 1b numbers could no longer be reproduced by anyone -- prose that
outlived the thing that justified it. Now it lives in the repo, tested.

A derived figure substitutes a rule's outcome into a *prior* run's per-case
record. It is exact where the rule's inputs are in the record and a bound where
they are not:

- ``intent.check()`` reads only the question, so its substitution is exact.
- The NO_DATA rule needs survivor unanimity, and a report written before
  per-candidate logging carries only the winner's agreement. Records at
  agreement 1.0 imply unanimity; below that it cannot be confirmed, hence an
  upper bound (every winner-empty entity-bound record flips) and a lower bound
  (agreement 1.0 only). Reports written after per-candidate logging carry
  ``candidates`` and need no replay: their figures are measured.
- Repair needs generation and cannot be replayed at all; every derived figure
  assumes it changes nothing.

Usage: ``python evals/replay_derived.py reports/eval_bridges2_qwen3_30b.jsonl``
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from evals.abstain_scoring import compute_abstain_metrics
from ledgerql import intent
from ledgerql.result_shape import (
    is_empty_or_null,
    is_identity_anchored_empty,
    is_tautologically_empty,
)


def load_report(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_gold(path: Path = Path("evals/gold.jsonl")) -> dict:
    return {c["id"]: c for c in (json.loads(line) for line in Path(path).read_text().splitlines())}


def _as_abstain(record: dict, reason_code: str) -> dict:
    record["answer"] = None
    record["reason_code"] = reason_code
    return record


def with_intent(records: list[dict], gold: dict) -> list[dict]:
    """Substitute ``intent.check()``'s outcome for cases it refuses. Exact: its
    input is the question text and its logic is a regex."""
    out = []
    for r in copy.deepcopy(records):
        result = intent.check(gold[r["id"]]["question"])
        if not result.ok:
            r = _as_abstain(r, result.reason_code)
            r["rows"], r["columns"] = [], []
        out.append(r)
    return out


def _rows(record: dict) -> list[tuple]:
    return [tuple(row) for row in record.get("rows") or []]


def apply_naive_empty_rule(records: list[dict]) -> tuple[list[dict], list[str]]:
    """The rule that does NOT work (spec 1b): any answered record whose winner is
    empty/all-NULL becomes NO_DATA. Kept because it is the counter-example that
    justifies the entity-bound rule: it also flips G06, where none is the answer."""
    out, flips = copy.deepcopy(records), []
    for r in out:
        if r["reason_code"] is None and r["answer"] is not None and is_empty_or_null(_rows(r)):
            flips.append(r["id"])
            _as_abstain(r, "NO_DATA")
    return out, flips


def apply_entity_bound_rule(
    records: list[dict], *, lower_bound: bool = False
) -> tuple[list[dict], list[str]]:
    """The shipped NO_DATA rule, replayed from winner-only records: an answered
    or ``LOW_AGREEMENT`` record whose winner is empty/all-NULL on an entity-bound
    query becomes NO_DATA. ``lower_bound`` keeps only agreement 1.0, where
    survivor unanimity is implied."""
    out, flips = copy.deepcopy(records), []
    for r in out:
        eligible = (r["reason_code"] is None and r["answer"] is not None) or (
            r["reason_code"] == "LOW_AGREEMENT"
        )
        if not eligible or not is_identity_anchored_empty(r["generated_sql"], _rows(r)):
            continue
        if lower_bound and r.get("confidence") != 1.0:
            continue
        flips.append(r["id"])
        _as_abstain(r, "NO_DATA")
    return out, flips


def apply_tautology_rule(records: list[dict]) -> tuple[list[dict], list[str]]:
    """An answered record whose SQL is constant-false/NULL and whose result is
    empty becomes SCHEMA_MISMATCH (the generator refusing in SQL)."""
    out, flips = copy.deepcopy(records), []
    for r in out:
        if (
            r["reason_code"] is None
            and r["answer"] is not None
            and is_tautologically_empty(r["generated_sql"])
            and not _rows(r)
        ):
            flips.append(r["id"])
            _as_abstain(r, "SCHEMA_MISMATCH")
    return out, flips


def _summarise(label: str, records: list[dict], gold: dict, flips: list[str]) -> dict:
    m = compute_abstain_metrics(records, gold)
    g06 = next((r for r in records if r["id"] == "G06"), None)
    return {
        "label": label,
        "flips": flips,
        "precision_decision": m["abstain_precision_decision"],
        "precision_strict": m["abstain_precision_strict"],
        "recall_decision": m["abstain_recall_decision"],
        "recall_strict": m["abstain_recall_strict"],
        "reason_correct": m["strict_correct_abstains"],
        "reason_denominator": m["decision_correct_abstains"],
        "reason_code_accuracy": m["reason_code_accuracy"],
        "all_abstains": m["all_abstains"],
        "g06_answered": None if g06 is None else g06["answer"] is not None,
    }


def derive_table(report: Path, gold: dict) -> list[dict]:
    base = with_intent(load_report(report), gold)
    rows = [_summarise("baseline (+intent)", base, gold, [])]
    naive, f = apply_naive_empty_rule(base)
    rows.append(_summarise("naive: any empty/all-NULL -> NO_DATA", naive, gold, f))
    for tag, lower in (("upper", False), ("lower", True)):
        eb, f = apply_entity_bound_rule(base, lower_bound=lower)
        rows.append(_summarise(f"entity-bound NO_DATA ({tag} bound)", eb, gold, f))
        both, f2 = apply_tautology_rule(eb)
        rows.append(_summarise(f"+ tautology check ({tag} bound)", both, gold, f2))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    args = ap.parse_args(argv)
    print(f"DERIVED from {args.report} (replay, not a measurement)\n")
    header = (
        f"{'rule':40} {'prec(dec)':>9} {'recall(dec)':>11} {'reason-correct':>16} {'abst':>5}  G06"
    )
    print(header)
    for r in derive_table(args.report, load_gold(args.gold)):
        rc = f"{r['reason_correct']}/{r['reason_denominator']}={r['reason_code_accuracy']:.1%}"
        g = {True: "answered", False: "BROKEN", None: "-"}[r["g06_answered"]]
        print(
            f"{r['label']:40} {r['precision_decision']:>9.1%} {r['recall_decision']:>11.1%} "
            f"{rc:>16} {r['all_abstains']:>5}  {g}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
