"""The audit that produced gold v2: what candidates did on cases nobody solved.

Ported from four scratch scripts (audit8, keys, j04, scale) so the evidence behind
`gold_v2.jsonl` survives the session. It reads the tracked bake-off evidence
(`reports/bakeoff_candidates.jsonl`, see evals/bakeoff_evidence.py) and executes
every candidate locally.

    python -m evals.gold_audit never-solved            # which cases no candidate solved
    python -m evals.gold_audit dump A09 J05            # result clusters and example SQL
    python -m evals.gold_audit outcomes A09 J04 ...    # outcomes against the v2 gold
    python -m evals.gold_audit scale R02 R04 T01 ...   # fraction vs percentage returned
    python -m evals.gold_audit goodwill                # J04: five readings of "most recent 10-K"

`outcomes` buckets each candidate against the case's v2 gold: `rejected` (guard or
execution error), `empty`, `strict` (matches the headline comparator; split by the
identifier type it matched through), `relaxed` (matches only if extra columns are
ignored) and `miss`.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter

import duckdb

from evals import bakeoff_evidence
from evals.passn_scoring import _run_candidate
from evals.scoring import case_match, load_gold

DEFAULT_DB = "data/ledgerql.duckdb"


def _connect(db: str):
    return duckdb.connect(db, read_only=True, config={"enable_external_access": "false"})


def candidate_results(evidence: list[dict], case_id: str, db: str):
    """Yield (model, profile, sql, rows or None) for every candidate of one case."""
    for rec in evidence:
        if rec["id"] != case_id:
            continue
        for sql in rec["sqls"]:
            _, rows = _run_candidate(sql, db)
            yield rec["model"], rec["profile"], sql, rows


def solved_cases(evidence: list[dict], cases: dict[str, dict], db: str) -> dict[str, int]:
    """{case id: number of candidates that match it (strict)} over ANSWER cases."""
    con = _connect(db)
    try:
        out = {}
        for cid, case in cases.items():
            if case["expected"] != "ANSWER":
                continue
            gold = con.execute(case["gold_sql"]).fetchall()
            out[cid] = sum(
                rows is not None and case_match(case, gold, rows, db).matched
                for _, _, _, rows in candidate_results(evidence, cid, db)
            )
        return out
    finally:
        con.close()


def result_clusters(evidence: list[dict], case_id: str, db: str) -> list[tuple[str, int, str]]:
    """Candidates grouped by the first rows they return: (rows, count, example SQL)."""
    counts: Counter = Counter()
    example: dict[str, str] = {}
    for _, _, sql, rows in candidate_results(evidence, case_id, db):
        key = "REJECTED/ERROR" if rows is None else json.dumps(rows[:4], default=str)
        counts[key] += 1
        example.setdefault(key, sql)
    return [(k, n, example[k]) for k, n in counts.most_common()]


def outcomes(evidence: list[dict], case: dict, db: str) -> Counter:
    """Bucket every candidate of one case against its gold (see module docstring)."""
    con = _connect(db)
    try:
        gold = con.execute(case["gold_sql"]).fetchall()
    finally:
        con.close()
    buckets: Counter = Counter()
    for _, _, _, rows in candidate_results(evidence, case["id"], db):
        if rows is None:
            buckets["rejected"] += 1
        elif not rows:
            buckets["empty"] += 1
        else:
            strict = case_match(case, gold, rows, db, mode="strict")
            if strict.matched:
                via = "+".join(sorted(strict.via)) or "plain"
                buckets["strict"] += 1
                buckets[f"strict via {via}"] += 1
            elif case_match(case, gold, rows, db, mode="relaxed").matched:
                buckets["relaxed"] += 1
            else:
                buckets["miss"] += 1
    return buckets


def scale_profile(evidence: list[dict], case: dict, db: str) -> Counter:
    """For a proportion case (v1 gold ends in a percentage): does each candidate's first
    row hold the gold value (`percent`) or a hundredth of it (`fraction`)?"""
    con = _connect(db)
    try:
        gold = con.execute(case["gold_sql"]).fetchall()
    finally:
        con.close()
    floats = [v for row in gold for v in row if isinstance(v, float)]
    target = floats[-1] if floats else None
    tally: Counter = Counter()
    for _, _, _, rows in candidate_results(evidence, case["id"], db):
        if not rows:
            tally["no rows"] += 1
            continue
        tag = "no numeric"
        for v in (v for v in rows[0] if isinstance(v, float)):
            if target and math.isclose(v, target, rel_tol=1e-3):
                tag = "percent"
            elif target and math.isclose(v * 100, target, rel_tol=1e-3):
                tag = "fraction"
        tally[tag] += 1
    return tally


def goodwill_definitions(db: str, threshold: float = 30e9) -> dict[str, set[str]]:
    """J04: the names above `threshold` under five readings of "most recent 10-K".
    If they all agree the gold's logic is not the problem."""
    con = _connect(db)
    q = lambda sql: {r[0] for r in con.execute(sql, [threshold]).fetchall()}  # noqa: E731
    try:
        base = (
            "FROM financial_facts ff JOIN filings fl ON fl.adsh=ff.adsh "
            "JOIN companies c ON c.cik=ff.cik WHERE ff.tag='Goodwill' AND ff.value>?"
        )
        return {
            "fiscal_year": q(
                f"SELECT DISTINCT c.name {base} AND ff.qtrs=0 AND fl.fiscal_year="
                "(SELECT MAX(f2.fiscal_year) FROM filings f2 "
                "WHERE f2.cik=ff.cik AND f2.form='10-K')"
            ),
            "filed_date": q(
                f"SELECT DISTINCT c.name {base} AND ff.qtrs=0 AND fl.form='10-K' AND fl.filed_date="
                "(SELECT MAX(f2.filed_date) FROM filings f2 "
                "WHERE f2.cik=ff.cik AND f2.form='10-K')"
            ),
            "period_end_date": q(
                f"SELECT DISTINCT c.name {base} AND fl.form='10-K' AND fl.period_end_date="
                "(SELECT MAX(f2.period_end_date) FROM filings f2 "
                "WHERE f2.cik=ff.cik AND f2.form='10-K')"
            ),
            "max ddate of the tag": q(
                "SELECT DISTINCT c.name FROM financial_facts ff JOIN companies c ON c.cik=ff.cik "
                "WHERE ff.tag='Goodwill' AND ff.value>? AND ff.ddate="
                "(SELECT MAX(f2.ddate) FROM financial_facts f2 "
                "WHERE f2.cik=ff.cik AND f2.tag='Goodwill')"
            ),
            "any year": q(
                "SELECT DISTINCT c.name FROM financial_facts ff JOIN companies c ON c.cik=ff.cik "
                "WHERE ff.tag='Goodwill' AND ff.value>?"
            ),
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ns = sub.add_parser("never-solved")
    ns.add_argument("--gold-version", choices=("v1", "v2"), default="v1")
    for name in ("dump", "outcomes", "scale"):
        sub.add_parser(name).add_argument("cases", nargs="+")
    sub.add_parser("goodwill")
    args = ap.parse_args(argv)

    if args.cmd == "goodwill":
        sets = goodwill_definitions(args.db)
        reference = sets["fiscal_year"]
        for name, names in sets.items():
            print(
                f"{name:<22} {len(names):>3} companies, same as fiscal_year: {names == reference}"
            )
        return 0

    evidence = bakeoff_evidence.load()
    if args.cmd == "never-solved":
        counts = solved_cases(evidence, load_gold(args.gold_version), args.db)
        never = sorted(c for c, n in counts.items() if n == 0)
        print(f"gold {args.gold_version}: {len(counts) - len(never)}/{len(counts)} solved by some")
        print(f"never solved ({len(never)}): {never}")
        return 0
    v1, v2 = load_gold("v1"), load_gold("v2")
    for cid in args.cases:
        print(f"\n== {cid}: {v1[cid]['question']}")
        if args.cmd == "dump":
            for rows, n, sql in result_clusters(evidence, cid, args.db):
                print(f"  x{n}: {rows[:200]}\n      {' '.join(sql.split())[:300]}")
        elif args.cmd == "outcomes":
            print(f"  {dict(outcomes(evidence, v2[cid], args.db))}")
        else:
            print(f"  {dict(scale_profile(evidence, v1[cid], args.db))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
