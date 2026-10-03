# ruff: noqa: E501  (report format strings are single lines)
"""Why did a run abstain `NO_DATA`? How many of those were an entity problem?

`NO_DATA` means every candidate that executed came back empty. Two quite different things produce
that: the data really is absent (JPMorgan has no revenue rows, so abstaining is right) or a candidate
looked up the wrong entity (`name = 'The Coca-Cola Company'`, stored `Coca-Cola Company (The)`; or a
ticker `'BRK-A'`, stored `BRK.B`), which entity linking targets. This separates them for the
candidates of each `NO_DATA` abstain and, as a bound, rewrites every name predicate to the case's own
ticker ("perfect linking"), re-executes, and reports whether anything then returns rows.

    python -m evals.nodata_audit reports/eval_bridges2_qwen25_32b_pipeline_47314855.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from evals.entity_upper_bound import case_companies
from evals.passn_scoring import _run_candidate_ex

DEFAULT_DB = "data/ledgerql.duckdb"


def _parse(sql: str | None):
    try:
        return sqlglot.parse_one(sql or "", read="duckdb")
    except Exception:  # noqa: BLE001
        return None


def _column(node, name: str):
    while isinstance(node, (exp.Lower, exp.Upper, exp.Trim)):
        node = node.this
    return node if isinstance(node, exp.Column) and node.name.lower() == name else None


def _predicates(tree, column: str):
    for n in tree.find_all(exp.EQ, exp.Like, exp.ILike, exp.In):
        col = _column(n.this, column)
        if col is not None:
            lits = n.expressions if isinstance(n, exp.In) else [n.args.get("expression")]
            yield n, col, [
                lit.this for lit in lits if isinstance(lit, exp.Literal) and lit.is_string
            ]


def _perfect_link(sql: str, ticker: str) -> str:
    tree = _parse(sql)
    if tree is None:
        return sql
    changed = False
    for node, col, _ in list(_predicates(tree, "name")):
        node.replace(
            exp.EQ(
                this=exp.column("ticker", table=col.table or None),
                expression=exp.Literal.string(ticker),
            )
        )
        changed = True
    return tree.sql(dialect="duckdb") if changed else sql


def classify(record: dict, stored_names: list[str], ticker: str | None, db_path: str) -> dict:
    """Per-record: how many candidates were empty, how many of those used a name literal that is not
    the stored name (or a ticker literal that is not the company's), and what perfect linking gives.
    """
    cands = record.get("candidates") or []
    empties = [c for c in cands if c.get("empty")]

    def wrong(column: str, c: dict, truth: list[str]) -> bool:
        tree = _parse(c["sql"])
        return tree is not None and any(
            lit not in truth for _, _, lits in _predicates(tree, column) for lit in lits
        )

    wrong_name = [c for c in empties if wrong("name", c, stored_names)]
    wrong_ticker = [c for c in empties if wrong("ticker", c, [ticker] if ticker else [])]
    linked_rows = 0
    if ticker:
        for c in cands:
            new = _perfect_link(c["sql"], ticker)
            if new != c["sql"]:
                _, rows, _ = _run_candidate_ex(new, db_path)
                linked_rows += bool(rows)
    return {
        "empty": len(empties),
        "empty_with_wrong_name": len(wrong_name),
        "empty_with_wrong_ticker": len(wrong_ticker),
        "all_empties_wrong_name": bool(empties) and len(wrong_name) == len(empties),
        "linked_with_rows": linked_rows,
    }


def audit(run_file: Path, cases: dict[str, dict], db_path: str) -> dict:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        records = [json.loads(x) for x in Path(run_file).read_text().splitlines() if x.strip()]
        rows = {}
        for r in records:
            if (
                r.get("answer") is not None
                or r.get("reason_code") != "NO_DATA"
                or r["id"] not in cases
            ):
                continue
            comps = case_companies(cases[r["id"]].get("gold_sql"), con)
            names = [n for _, n in comps]
            ticker = comps[0][0] if len(comps) == 1 else None
            rows[r["id"]] = classify(r, names, ticker, db_path)
    finally:
        con.close()
    return {
        "nodata_abstains": len(rows),
        "all_empties_wrong_name": [i for i, c in rows.items() if c["all_empties_wrong_name"]],
        "some_wrong_name": [i for i, c in rows.items() if c["empty_with_wrong_name"]],
        "wrong_ticker": [i for i, c in rows.items() if c["empty_with_wrong_ticker"]],
        "perfect_linking_gives_rows": [i for i, c in rows.items() if c["linked_with_rows"]],
        "per_case": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_file", type=Path)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--gold", type=Path, default=Path(__file__).resolve().parent / "gold.jsonl")
    ap.add_argument("--expected", default="ANSWER_WITH_ASSUMPTION")
    args = ap.parse_args(argv)
    cases = {
        c["id"]: c
        for c in (json.loads(x) for x in args.gold.read_text().splitlines() if x.strip())
        if c["expected"] == args.expected
    }
    out = audit(args.run_file, cases, args.db)
    for i, c in out["per_case"].items():
        print(
            f"{i}: empty {c['empty']}/5, wrong name literal {c['empty_with_wrong_name']}, wrong ticker literal {c['empty_with_wrong_ticker']}, perfect linking returns rows on {c['linked_with_rows']} candidates"
        )
    print({k: v for k, v in out.items() if k != "per_case"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
