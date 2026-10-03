"""Structural rule for held-out gold: every acceptable alternative must be scoreable.

The dev gold's `M02` lists "ANSWER_WITH_ASSUMPTION using total_assets instead, if stated" as an
acceptable alternative. It is prose, and nothing can score a sentence: both measured models took
exactly that alternative and scored 0 (`evals/KNOWN_GOLD_ISSUES.md`). So in held-out gold:

- `accept_alternatives` may contain only `ABSTAIN:<REASON_CODE>` entries, which the abstain scorer
  parses;
- any acceptable *answer* is an entry of `alternatives`, with `describes` (prose, for humans),
  `gold_sql` (executable, so the comparator can credit it) and `compare`.

    python -m evals.heldout_gold_check evals/heldout_v1.jsonl [--db data/ledgerql.duckdb]

Exits 1 if any case breaks the rule. Run before the freeze (evals/HELDOUT_PROTOCOL.md 4.3).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

COMPARE_MODES = ("scalar", "scalar_or_null", "count", "set", "ordered", "empty", "none")
_ABSTAIN = re.compile(r"^ABSTAIN:[A-Z_]+$")


def check_case(case: dict, con=None) -> list[str]:
    problems = []
    for alt in case.get("accept_alternatives") or []:
        if not _ABSTAIN.match(alt):
            problems.append(
                f"accept_alternatives has prose the comparator cannot score ({alt!r}); an "
                "acceptable answer must be an entry of `alternatives` with its own executable "
                "gold_sql"
            )
    for i, alt in enumerate(case.get("alternatives") or []):
        for field in ("describes", "gold_sql", "compare"):
            if not alt.get(field):
                problems.append(f"alternatives[{i}] is missing `{field}`")
        if alt.get("compare") and alt["compare"] not in COMPARE_MODES:
            problems.append(f"alternatives[{i}].compare {alt['compare']!r} is not a compare mode")
        if con is not None and alt.get("gold_sql"):
            try:
                con.execute(alt["gold_sql"]).fetchall()
            except Exception as e:  # noqa: BLE001
                problems.append(f"alternatives[{i}].gold_sql does not execute: {e}")
    return problems


def check_file(path: Path, con=None) -> dict[str, list[str]]:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            case = json.loads(line)
            found = check_case(case, con)
            if found:
                out[case["id"]] = found
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gold", type=Path)
    ap.add_argument("--db", help="also execute every alternative's gold SQL against this database")
    args = ap.parse_args(argv)
    con = None
    if args.db:
        import duckdb

        con = duckdb.connect(args.db, read_only=True, config={"enable_external_access": "false"})
    bad = check_file(args.gold, con)
    for cid, problems in bad.items():
        for p in problems:
            print(f"{cid}: {p}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
