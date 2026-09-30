# ruff: noqa: E501  (markdown table rows are single lines)
"""What would perfect entity linking gain? Offline, no GPU.

Many candidates fail only because they compare `companies.name` to a spelling that is
not stored (`name = 'Microsoft Corporation'`, stored `Microsoft`), so they return
nothing. For each candidate this rewrites every predicate of the form
`name = '...'`, `name LIKE '%...%'`, `name ILIKE ...`, `LOWER(name) LIKE ...` or
`name IN (...)` whose literal names one of the case's companies into
`ticker = '<TICKER>'`, re-executes it, and re-scores. The companies of a case are read
from its gold SQL, so the link is always right: the result is an upper bound on what
a linker could gain, not an estimate of what one will.

    python -m evals.entity_upper_bound --write reports/entity_upper_bound.md
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import duckdb
import sqlglot
from sqlglot import exp

from evals.rescore_v2 import (
    DEFAULT_DB,
    LABELS,
    MODEL_NAMES,
    VERSIONS,
    Gold,
    load_evidence,
    passn_table,
    score_bakeoff,
    union_solved,
)
from ledgerql.entity_link import same_company

_TICKER_EQ = re.compile(r"ticker\s*=\s*'([A-Z0-9.\-]+)'")
_TICKER_IN = re.compile(r"ticker\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
_NAME_SEARCH = re.compile(r"name\s+I?LIKE\s+'%([^%']+)%'", re.IGNORECASE)


def case_companies(gold_sql: str | None, con) -> list[tuple[str, str]]:
    """The (ticker, stored name) of every company a gold query names, by ticker literal or
    by name search. Empty for a question about no particular company."""
    if not gold_sql:
        return []
    tickers = list(_TICKER_EQ.findall(gold_sql))
    for group in _TICKER_IN.findall(gold_sql):
        tickers += re.findall(r"'([^']+)'", group)
    for term in _NAME_SEARCH.findall(gold_sql):
        tickers += [
            t
            for (t,) in con.execute(
                "SELECT ticker FROM companies WHERE name ILIKE ?", [f"%{term}%"]
            ).fetchall()
        ]
    out = []
    for t in dict.fromkeys(tickers):
        row = con.execute("SELECT ticker, name FROM companies WHERE ticker = ?", [t]).fetchone()
        if row:
            out.append((row[0], row[1]))
    return out


def _name_column(node) -> exp.Column | None:
    while isinstance(node, (exp.Lower, exp.Upper, exp.Trim)):
        node = node.this
    if isinstance(node, exp.Column) and node.name.lower() == "name":
        return node
    return None


def _ticker_for(literal: str, companies: list[tuple[str, str]]) -> str | None:
    literal = literal.strip("%").strip()
    for ticker, stored in companies:
        if literal.upper() == ticker or same_company(literal, stored):
            return ticker
    return None


def rewrite_name_predicates(sql: str, companies: list[tuple[str, str]]) -> str:
    """`sql` with every name predicate whose literal names one of `companies` turned into a
    ticker predicate. Anything it cannot parse or match is returned unchanged."""
    if not companies:
        return sql
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001 - unparseable candidates are scored as they are
        return sql
    if tree is None:
        return sql
    changed = False
    for node in list(tree.find_all(exp.EQ, exp.Like, exp.ILike, exp.In)):
        col = _name_column(node.this)
        if col is None:
            continue
        ticker_col = exp.column("ticker", table=col.table or None)
        if isinstance(node, exp.In):
            literals = node.expressions
            if not literals or not all(
                isinstance(x, exp.Literal) and x.is_string for x in literals
            ):
                continue
            tickers = [_ticker_for(x.this, companies) for x in literals]
            if any(t is None for t in tickers):
                continue
            node.replace(
                exp.In(this=ticker_col, expressions=[exp.Literal.string(t) for t in tickers])
            )
        else:
            lit = node.args.get("expression")
            if not (isinstance(lit, exp.Literal) and lit.is_string):
                continue
            ticker = _ticker_for(lit.this, companies)
            if ticker is None:
                continue
            node.replace(exp.EQ(this=ticker_col, expression=exp.Literal.string(ticker)))
        changed = True
    return tree.sql(dialect="duckdb") if changed else sql


def rewrite_evidence(evidence: list[dict], gold: Gold) -> tuple[list[dict], Counter]:
    """The bake-off evidence with every candidate's name predicates linked, and how many
    candidates that changed."""
    con = duckdb.connect(gold.db, read_only=True, config={"enable_external_access": "false"})
    stats: Counter = Counter()
    try:
        by_case = {cid: case_companies(c.get("gold_sql"), con) for cid, c in gold.v1.items()}
    finally:
        con.close()
    out = []
    for rec in evidence:
        companies = by_case.get(rec["id"], [])
        sqls = [rewrite_name_predicates(s, companies) for s in rec["sqls"]]
        stats["candidates"] += len(sqls)
        stats["rewritten"] += sum(a != b for a, b in zip(sqls, rec["sqls"], strict=True))
        out.append({**rec, "sqls": sqls, "orig_sqls": rec["sqls"]})
    return out, stats


def render(before, after, stats: Counter) -> str:
    tb, ta = passn_table(before), passn_table(after)
    lines = [
        "# Entity linking: the offline upper bound",
        "",
        "Every candidate's company-name predicates are rewritten to the correct ticker (the case's "
        "companies are read from its gold SQL, so the link is always right), re-executed and "
        "re-scored. This is what *perfect* linking could gain; it is not an estimate of what a "
        "linker will. `evals/entity_upper_bound.py`.",
        "",
        f"Candidates: {stats['candidates']}; changed by the rewrite: {stats['rewritten']}.",
        "",
        "## pass@1 -> pass@N, before | after linking",
        "",
        "| model | prompt | "
        + " | ".join(f"{LABELS[v]} before | {LABELS[v]} after" for v in VERSIONS)
        + " |",
        "|---|---|" + "---|---|" * len(VERSIONS),
    ]
    for key in sorted(tb):
        cells = []
        for v in VERSIONS:
            cells += [f"{tb[key][v][0]} -> {tb[key][v][1]}", f"{ta[key][v][0]} -> {ta[key][v][1]}"]
        lines.append(f"| {MODEL_NAMES[key[0]]} | {key[1]} | " + " | ".join(cells) + " |")
    lines += ["", "## Union over all nine runs", ""]
    for v in VERSIONS:
        ub, ua = union_solved(before, v), union_solved(after, v)
        lines.append(
            f"- {LABELS[v]}: {len(ub)} -> {len(ua)} of 50; newly solved {sorted(ua - ub)}; "
            f"never solved after: {sorted({p.id for p in after} - ua)}"
        )
    lines += ["", "## Candidates that flip, by case (v3 strict)", ""]
    gained: Counter = Counter()
    lost: Counter = Counter()
    for pb, pa in zip(before, after, strict=True):
        assert (pb.model, pb.profile, pb.id) == (pa.model, pa.profile, pa.id)
        for cb, ca in zip(pb.cands, pa.cands, strict=True):
            if ca.verdict["v3"] and not cb.verdict["v3"]:
                gained[pb.id] += 1
            if cb.verdict["v3"] and not ca.verdict["v3"]:
                lost[pb.id] += 1
    lines += ["| case | wrong -> right | right -> wrong |", "|---|---|---|"]
    for cid in sorted(set(gained) | set(lost)):
        lines.append(f"| {cid} | {gained[cid]} | {lost[cid]} |")
    lines += [
        "",
        f"Total: {sum(gained.values())} candidates gained, {sum(lost.values())} lost, "
        f"of {stats['candidates']}.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    gold = Gold(args.db)
    evidence = load_evidence()
    linked, stats = rewrite_evidence(evidence, gold)
    before, after = score_bakeoff(evidence, gold), score_bakeoff(linked, gold)
    text = render(before, after, stats)
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
