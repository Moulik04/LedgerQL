"""Gold v2: the comparator and the per-case conversion table.

The rules are evals/README.md section 6g, written and committed before this file
existed. Everything here follows them; nothing here was derived from what any
candidate returned. `CHANGES` is the conversion table: one row per case v2
changes, naming the rule behind each change. Cases not in it are copied from v1
untouched.

    python -m evals.gold_v2            # rewrite evals/gold_v2.jsonl from gold.jsonl
    python -m evals.gold_v2 --check    # exit 1 if the committed file differs

`match()` is the v2 comparator. `mode="strict"` is the headline: the candidate
returns exactly gold's columns, in gold's order. `mode="relaxed"` is the second,
labelled figure: gold's columns may sit anywhere among extra candidate columns.
"""

# ruff: noqa: E501  (the per-case SQL strings below are single literals so they read as gold)
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

GOLD_V1_PATH = Path(__file__).resolve().parent / "gold.jsonl"
GOLD_V2_PATH = Path(__file__).resolve().parent / "gold_v2.jsonl"

SCORED = ("ANSWER", "ANSWER_WITH_ASSUMPTION")
DEFAULT_TOLERANCE = 1e-6
MAX_RELAXED_COLUMNS = 16
RATIO_FACTORS = (1.0, 100.0, 0.01)


# --------------------------------------------------------------------------
# Entity resolution (V2)
# --------------------------------------------------------------------------


class EntityResolver:
    """Resolve a returned value to a company: an integer that is a `companies.cik`,
    else a value equal to a `companies.ticker`, else equal to a `companies.name`.
    Exact matches only. Returns (cik, identifier type) or None."""

    def __init__(self, companies: list[tuple[int, str, str]]):
        self._ciks = {cik for cik, _, _ in companies}
        self._tickers = {ticker: cik for cik, ticker, _ in companies}
        self._names = {name: cik for cik, _, name in companies}

    @classmethod
    def from_connection(cls, con) -> EntityResolver:
        return cls(con.execute("SELECT cik, ticker, name FROM companies").fetchall())

    def resolve(self, cell) -> tuple[int, str] | None:
        if cell is None or isinstance(cell, bool):
            return None
        if isinstance(cell, int) and cell in self._ciks:
            return cell, "cik"
        if isinstance(cell, str):
            if cell in self._tickers:
                return self._tickers[cell], "ticker"
            if cell in self._names:
                return self._names[cell], "name"
        return None


# --------------------------------------------------------------------------
# Comparator
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    matched: bool
    via: frozenset = frozenset()  # identifier types a candidate matched through (V2)


_NO = Match(False)


def _is_number(x) -> bool:
    return isinstance(x, (int, float, Decimal)) and not isinstance(x, bool)


def _close(gold, pred, tol: float) -> bool:
    g, p = float(gold), float(pred)
    return abs(p - g) <= max(abs(g) * tol, 1e-9)


def _cell_match(kind: str, gold, pred, tol: float, resolver: EntityResolver, via: set) -> bool:
    if kind == "entity":
        g = resolver.resolve(gold)
        if g is None:
            raise ValueError(f"gold entity cell {gold!r} does not resolve to a company")
        p = resolver.resolve(pred)
        if p is None or p[0] != g[0]:
            return False
        via.add(p[1])
        return True
    if gold is None or pred is None:
        return gold is None and pred is None
    if _is_number(gold) and _is_number(pred):
        if kind == "ratio":
            return any(_close(gold, float(pred) * f, tol) for f in RATIO_FACTORS)
        return _close(gold, pred, tol)
    return gold == pred


def _kinds(case: dict, width: int) -> list[str]:
    entity = set(case.get("entity_cols") or [])
    ratio = set(case.get("ratio_cols") or [])
    return ["entity" if j in entity else "ratio" if j in ratio else "plain" for j in range(width)]


def _row_match(kinds, grow, prow, tol, resolver, via) -> bool:
    if len(grow) != len(prow):
        return False
    return all(
        _cell_match(k, g, p, tol, resolver, via) for k, g, p in zip(kinds, grow, prow, strict=True)
    )


def _strict(case, gold_rows, pred_rows, resolver) -> Match:
    compare = case["compare"]
    tol = case.get("tolerance", DEFAULT_TOLERANCE)
    via: set = set()
    if compare in ("scalar", "count", "scalar_or_null"):
        if len(pred_rows) != 1 or len(pred_rows[0]) != 1:
            return _NO
        grow = tuple(gold_rows[0][:1]) if gold_rows else (None,)
        ok = _row_match(_kinds(case, 1), grow, tuple(pred_rows[0]), tol, resolver, via)
        return Match(ok, frozenset(via)) if ok else _NO
    if not gold_rows:
        return Match(not pred_rows)
    kinds = _kinds(case, len(gold_rows[0]))
    if compare == "ordered":
        if len(gold_rows) != len(pred_rows):
            return _NO
        ok = all(
            _row_match(kinds, g, p, tol, resolver, via)
            for g, p in zip(gold_rows, pred_rows, strict=True)
        )
        return Match(ok, frozenset(via)) if ok else _NO
    if compare == "set":
        # Set equality under tolerant cell equality: every gold row is matched by some
        # candidate row and every candidate row matches some gold row. Duplicates
        # collapse, as they did under v1's `set(...) == set(...)`.
        for g in gold_rows:
            if not any(_row_match(kinds, g, p, tol, resolver, set()) for p in pred_rows):
                return _NO
        for p in pred_rows:
            if not any(_row_match(kinds, g, p, tol, resolver, via) for g in gold_rows):
                return _NO
        return Match(True, frozenset(via))
    raise ValueError(f"unknown compare value: {compare!r}")


def match(
    case: dict, gold_rows: list, pred_rows: list, resolver: EntityResolver, mode: str = "strict"
) -> Match:
    """Does `pred_rows` answer `case`, given `gold_rows` (gold_sql executed)?"""
    compare = case["compare"]
    if compare == "none":
        return Match(True)
    if compare == "empty":
        return Match(len(pred_rows) == 0)
    gold_rows = [tuple(r) for r in gold_rows]
    pred_rows = [tuple(r) for r in pred_rows]
    if mode == "strict":
        return _strict(case, gold_rows, pred_rows, resolver)
    if mode != "relaxed":
        raise ValueError(f"unknown mode: {mode!r}")
    width = len(gold_rows[0]) if gold_rows else 1
    if not pred_rows:
        return _strict(case, gold_rows, pred_rows, resolver)
    n = len(pred_rows[0])
    if n < width or n > MAX_RELAXED_COLUMNS:
        return _NO
    for cols in itertools.permutations(range(n), width):
        projected = [tuple(row[c] for c in cols) for row in pred_rows]
        m = _strict(case, gold_rows, projected, resolver)
        if m.matched:
            return m
    return _NO


# --------------------------------------------------------------------------
# The conversion table: v1 -> v2, one row per changed case
# --------------------------------------------------------------------------

# Each entry: only the fields that change (`gold_sql`, `compare`, `tolerance`,
# `entity_cols`, `ratio_cols`) plus `rules`, the README 6g rules the change follows.
# V1 projection, V2 entity target, V3 ratio scale, V4 order and shape, V5 tolerance cap.
# V6 (tolerance in every mode) lives in the comparator, not in a per-case change.
CHANGES: dict[str, dict] = {
    # V1: the year behind "most recent" / the date behind "for 2024" is not asked for.
    "L03": {
        "gold_sql": "SELECT value FROM v_net_income WHERE ticker='MSFT' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "L04": {
        "gold_sql": "SELECT value FROM v_total_assets WHERE ticker='NVDA' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "L09": {
        "gold_sql": "SELECT value FROM v_cash WHERE ticker='XOM' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "J02": {
        "gold_sql": (
            "SELECT ff.value FROM financial_facts ff JOIN filings fl ON fl.adsh=ff.adsh "
            "WHERE ff.cik=(SELECT cik FROM companies WHERE ticker='MSFT') "
            "AND ff.tag='StockholdersEquity' AND ff.qtrs=0 ORDER BY fl.fiscal_year DESC LIMIT 1"
        ),
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "J06": {
        "gold_sql": (
            "SELECT ff.value FROM financial_facts ff JOIN filings fl ON fl.adsh=ff.adsh "
            "WHERE ff.cik=(SELECT cik FROM companies WHERE ticker='INTC') "
            "AND ff.tag='LongTermDebtNoncurrent' AND ff.qtrs=0 ORDER BY fl.fiscal_year DESC LIMIT 1"
        ),
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "G04": {
        "gold_sql": "SELECT value FROM v_total_assets WHERE ticker='PFE' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "M01": {
        "gold_sql": "SELECT value FROM v_revenue WHERE ticker='AAPL' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "U02": {
        "gold_sql": "SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2024",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "U07": {
        "gold_sql": "SELECT value/1000000.0 FROM v_revenue WHERE ticker='KO' ORDER BY fiscal_year DESC LIMIT 1",
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    "U08": {  # the question asks for the value and its unit; the year is not asked for
        "gold_sql": "SELECT value, uom FROM v_total_assets WHERE ticker='META' ORDER BY fiscal_year DESC LIMIT 1",
        "rules": ["V1"],
    },
    "M09": {  # revenue was asked; the ticker and year columns only qualified it
        "gold_sql": (
            "SELECT v.value FROM companies c LEFT JOIN v_revenue v "
            "ON v.cik=c.cik AND v.fiscal_year=2024 WHERE c.name ILIKE '%berkshire%'"
        ),
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    # V1 + V2: "which company" asks for the company, compared at company level.
    "A01": {
        "gold_sql": "SELECT name FROM v_revenue WHERE fiscal_year=2024 ORDER BY value DESC LIMIT 10",
        "entity_cols": [0],
        "rules": ["V1", "V2"],
    },
    "A09": {
        "gold_sql": "SELECT DISTINCT name FROM v_revenue WHERE value>300000000000",
        "compare": "set",  # V4: the question asks for no order
        "entity_cols": [0],
        "rules": ["V1", "V2", "V4"],
    },
    "J04": {
        "gold_sql": (
            "SELECT DISTINCT c.name FROM financial_facts ff JOIN filings fl ON fl.adsh=ff.adsh "
            "JOIN companies c ON c.cik=ff.cik WHERE ff.tag='Goodwill' AND ff.qtrs=0 "
            "AND ff.value>30000000000 AND fl.fiscal_year=(SELECT MAX(fl2.fiscal_year) "
            "FROM filings fl2 WHERE fl2.cik=ff.cik AND fl2.form='10-K')"
        ),
        "entity_cols": [0],
        "rules": ["V1", "V2"],
    },
    "M02": {
        "gold_sql": (
            "SELECT name FROM v_revenue WHERE fiscal_year=(SELECT MAX(fiscal_year) FROM v_revenue) "
            "ORDER BY value DESC LIMIT 1"
        ),
        "compare": "scalar",
        "entity_cols": [0],
        "rules": ["V1", "V2", "V4"],
    },
    "R04": {
        "gold_sql": (
            "SELECT r.name FROM v_revenue r JOIN v_net_income n ON n.cik=r.cik "
            "AND n.fiscal_year=r.fiscal_year WHERE r.fiscal_year=2024 AND r.value>100000000000 "
            "ORDER BY n.value/r.value DESC LIMIT 1"
        ),
        "compare": "scalar",
        "entity_cols": [0],
        "rules": ["V1", "V2", "V4"],
    },
    "T02": {
        "gold_sql": (
            "WITH a AS (SELECT cik, value FROM v_revenue WHERE fiscal_year=2024), "
            "b AS (SELECT cik, value, name FROM v_revenue WHERE fiscal_year=2025) "
            "SELECT b.name FROM a JOIN b ON a.cik=b.cik ORDER BY (b.value-a.value)/a.value DESC LIMIT 1"
        ),
        "compare": "scalar",
        "entity_cols": [0],
        "rules": ["V1", "V2", "V4"],
    },
    "T07": {"entity_cols": [0], "rules": ["V2"]},
    "G02": {"entity_cols": [0], "rules": ["V2"]},
    # V1: the sector is the answer; the average behind the ranking is not asked for.
    "A11": {
        "gold_sql": (
            "SELECT c.gics_sector FROM v_net_income v JOIN companies c ON c.cik=v.cik "
            "WHERE v.fiscal_year=2024 GROUP BY 1 ORDER BY AVG(v.value) DESC LIMIT 1"
        ),
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    # V1: accession number and fiscal year were asked for; the filing date was not.
    "J05": {
        "gold_sql": (
            "SELECT adsh, fiscal_year FROM filings WHERE cik=(SELECT cik FROM companies "
            "WHERE ticker='TSLA') AND form='10-K' ORDER BY filed_date"
        ),
        "rules": ["V1"],
    },
    # V1: the inputs behind a difference are not asked for.
    "G05": {
        "gold_sql": (
            "WITH a AS (SELECT value FROM v_revenue WHERE ticker='AMZN' ORDER BY fiscal_year DESC LIMIT 1), "
            "w AS (SELECT value FROM v_revenue WHERE ticker='WMT' ORDER BY fiscal_year DESC LIMIT 1) "
            "SELECT a.value-w.value FROM a, w"
        ),
        "compare": "scalar",
        "rules": ["V1", "V4"],
    },
    # V4: "side by side" asks for no order.
    "T03": {"compare": "set", "rules": ["V4"]},
    # V3: proportions.
    "T01": {"ratio_cols": [0], "rules": ["V3"]},
    "R01": {"ratio_cols": [0], "rules": ["V3"]},
    "R02": {"ratio_cols": [0], "rules": ["V3"]},
    "R03": {"ratio_cols": [0], "rules": ["V3"]},
    "R05": {"ratio_cols": [0], "rules": ["V3"]},
    "R06": {"entity_cols": [0], "ratio_cols": [1], "rules": ["V2", "V3"]},
    "G01": {"ratio_cols": [2], "rules": ["V3"]},
    "R07": {  # the margin is asked for; it is NULL because revenue is absent
        "gold_sql": (
            "SELECT 100.0*n.value/r.value FROM v_net_income n LEFT JOIN v_revenue r "
            "ON r.cik=n.cik AND r.fiscal_year=n.fiscal_year WHERE n.ticker='JPM' AND n.fiscal_year=2024"
        ),
        "compare": "scalar_or_null",
        "ratio_cols": [0],
        "rules": ["V1", "V3", "V4"],
    },
    # V3 + V5: percentages, with the tolerance cap.
    "A10": {"ratio_cols": [0], "tolerance": 0.05, "rules": ["V3", "V5"]},
    "C04": {"ratio_cols": [0], "tolerance": 0.05, "rules": ["V3", "V5"]},
}


def build_gold_v2(v1_cases: list[dict]) -> list[dict]:
    """v1 cases with `CHANGES` applied. Unchanged cases are returned as they are."""
    unknown = set(CHANGES) - {c["id"] for c in v1_cases}
    if unknown:
        raise ValueError(f"CHANGES names cases that are not in gold: {sorted(unknown)}")
    out = []
    for case in v1_cases:
        change = CHANGES.get(case["id"])
        if change is None:
            out.append({**case, "gold_version": "v2"})
            continue
        new = {**case, "gold_version": "v2"}
        meta = {
            "rules": change["rules"],
            "v1_gold_sql": case.get("gold_sql"),
            "v1_compare": case["compare"],
        }
        if "tolerance" in change:
            meta["v1_tolerance"] = case.get("tolerance")
        for key in ("gold_sql", "compare", "tolerance"):
            if key in change:
                new[key] = change[key]
        new["entity_cols"] = change.get("entity_cols", [])
        new["ratio_cols"] = change.get("ratio_cols", [])
        new["v2"] = meta
        out.append(new)
    return out


def load_v1() -> list[dict]:
    return [json.loads(line) for line in GOLD_V1_PATH.read_text().splitlines() if line.strip()]


def render(cases: list[dict]) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(build_gold_v2(load_v1()))
    if args.check:
        same = GOLD_V2_PATH.exists() and GOLD_V2_PATH.read_text() == text
        print("gold_v2.jsonl is up to date" if same else "gold_v2.jsonl differs from the builder")
        return 0 if same else 1
    GOLD_V2_PATH.write_text(text)
    print(f"wrote {GOLD_V2_PATH} ({len(CHANGES)} cases changed of {text.count(chr(10))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
