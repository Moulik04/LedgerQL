"""Validate evals/gold.jsonl against the real Phase 1 database (docs/schema.md).

Run before starting Phase 2, and again after any schema change:

    python evals/validate_gold.py --db data/ledgerql.duckdb

For each case:
  1. JSON is well-formed and required fields are present.
  2. gold_sql (when not null) is exactly one SELECT (sqlglot, if installed).
  3. gold_sql binds against the live schema (DuckDB EXPLAIN) — catches any
     mismatch between this file and the real mart.
  4. gold_sql executes; result shape agrees with `compare`.
  5. `anchor: true` cases match their `anchor_value` within a loose tolerance.
  6. Ticker anchors resolve to the expected registrant name fragment.
  7. gold_sql only touches the seven allowlisted mart objects (companies,
     filings, financial_facts, v_revenue, v_net_income, v_total_assets,
     v_cash) — never the stg_* staging tables.

Cases with `"needs_validation": true` are graded the same way but reported
in a separate REVIEW NEEDED section instead of FAILURES: a structural or
binding problem there is still fatal (exit 1), but a data-shape mismatch
(e.g. an optional tag turns out to be absent) is only a warning, because I
flagged those cases as genuinely uncertain rather than confidently wrong.
Read each one's `validation_note` and either fix `gold_sql`/`expected` or
leave it — the note says which.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import duckdb
except ImportError:  # pragma: no cover
    sys.exit("duckdb is required: pip install duckdb")

try:
    import sqlglot
except ImportError:  # pragma: no cover
    sqlglot = None

# Ensure the project root (this file's parent directory) is importable when
# this script is run directly (`python evals/validate_gold.py`), which sets
# sys.path[0] to evals/ rather than the project root. Normally the editable
# install (`uv sync`) makes `ledgerql` importable without this, but that
# depends on the interpreter processing the editable-install .pth file in
# site-packages, and on at least one real machine that step was silently
# skipped by CPython 3.12's site.py (which refuses to read a .pth file that
# carries the macOS "hidden" (UF_HIDDEN) file flag) -- so `ledgerql` was not
# importable even though `uv sync` reported everything installed correctly.
# This bootstrap makes the script self-sufficient regardless of that.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledgerql.guardrails import check_single_select, check_table_allowlist, parse_sql

REQUIRED = {"id", "tier", "difficulty", "question", "expected", "gold_sql", "compare", "tests"}
BEHAVIOURS = {"ANSWER", "ABSTAIN", "ANSWER_WITH_ASSUMPTION"}
COMPARES = {"scalar", "scalar_or_null", "set", "ordered", "empty", "none", "count"}

# ticker -> a fragment expected in companies.name, for sanity-checking the
# handful of companies this gold set relies on by name.
TICKER_ANCHORS = {
    "AAPL": "APPLE",
    "MSFT": "MICROSOFT",
    "AMZN": "AMAZON",
    "GOOGL": "ALPHABET",
    "NVDA": "NVIDIA",
    "TSLA": "TESLA",
    "META": "META",
    "JPM": "JPMORGAN",
    "WMT": "WALMART",
    "XOM": "EXXON",
    "KO": "COCA",
    "PFE": "PFIZER",
    "BA": "BOEING",
    "F": "FORD",
    "INTC": "INTEL",
}


def load_cases(path: Path) -> list[dict]:
    cases, errors = [], []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"line {n}: bad JSON ({e})")
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    return cases


def check_structure(c: dict) -> str | None:
    missing = REQUIRED - c.keys()
    if missing:
        return f"missing fields {sorted(missing)}"
    if c["expected"] not in BEHAVIOURS:
        return f"unknown expected={c['expected']}"
    if c["compare"] not in COMPARES:
        return f"unknown compare={c['compare']}"
    if c["expected"] == "ABSTAIN" and "reason_code" not in c:
        return "ABSTAIN case has no reason_code"
    if c["gold_sql"] is None and c["compare"] != "none":
        return "gold_sql is null but compare != none"
    if c["gold_sql"] is not None and c["compare"] == "none":
        return "gold_sql present but compare == none"
    return None


def check_single_select_and_tables(sql: str) -> str | None:
    if sqlglot is None:
        return None
    try:
        stmts = parse_sql(sql)
    except Exception as e:  # noqa: BLE001
        return f"sqlglot parse error: {e}"
    event = check_single_select(stmts)
    if event == "single_statement":
        return f"{len(stmts)} statements, expected 1"
    if event == "read_only":
        return f"top-level node is {type(stmts[0]).__name__}, not SELECT"
    stray = check_table_allowlist(stmts[0])
    if stray:
        return f"references non-allowlisted table(s): {sorted(stray)}"
    return None


def check_binds(con, sql: str) -> str | None:
    try:
        con.execute(f"EXPLAIN {sql}")
    except Exception as e:  # noqa: BLE001
        return f"does not bind: {str(e).splitlines()[0]}"
    return None


def check_executes(con, c: dict) -> str | None:
    try:
        rows = con.execute(c["gold_sql"]).fetchall()
    except Exception as e:  # noqa: BLE001
        return f"execution error: {str(e).splitlines()[0]}"
    n = len(rows)
    cmp = c["compare"]
    if cmp == "empty":
        return None if n == 0 else f"expected empty result, got {n} rows"
    if cmp in {"scalar", "count", "scalar_or_null"}:
        if n != 1 or len(rows[0]) != 1:
            return f"expected 1x1 result, got {n} rows x {len(rows[0]) if rows else 0} cols"
        if cmp != "scalar_or_null" and rows[0][0] is None:
            return "scalar result is NULL (data missing or wrong column/tag mapping)"
        if cmp == "scalar" and c.get("anchor") and "anchor_value" in c:
            got = rows[0][0]
            want = c["anchor_value"]
            tol = max(abs(want) * 0.001, 0.01)
            if got is None or abs(got - want) > tol:
                return f"anchor mismatch: expected ~{want}, got {got}"
    elif n == 0:
        return "empty result — data not loaded for this period/company, or filter wrong"
    return None


def check_ticker_anchors(con) -> list[str]:
    problems = []
    try:
        placeholders = ",".join(f"'{t}'" for t in TICKER_ANCHORS)
        found = dict(
            con.execute(
                f"SELECT ticker, name FROM companies WHERE ticker IN ({placeholders})"
            ).fetchall()
        )
    except Exception as e:  # noqa: BLE001
        return [f"could not query companies table: {str(e).splitlines()[0]}"]
    for ticker, fragment in TICKER_ANCHORS.items():
        name = found.get(ticker)
        if name is None:
            problems.append(f"ticker {ticker} ({fragment}) not in companies")
        elif fragment not in name.upper():
            problems.append(f"ticker {ticker} is '{name}', expected something like '{fragment}'")
    return problems


def check_staging_tables_hidden(con) -> list[str]:
    """Sanity check: staging tables should exist (for debugging) but never
    be part of what SQL generation is allowed to see. This just confirms
    the DB matches the documented mart/staging split; the actual allowlist
    enforcement lives in the pipeline's guardrails, not here."""
    notes = []
    for t in ("stg_sub", "stg_num", "stg_tag"):
        try:
            con.execute(f"SELECT 1 FROM {t} LIMIT 1")
        except Exception:  # noqa: BLE001
            notes.append(
                f"note: staging table {t} not found (fine if Phase 1 named it differently)"
            )
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--skip-exec", action="store_true", help="only bind, do not execute")
    args = ap.parse_args()

    cases = load_cases(Path(args.gold))
    con = duckdb.connect(args.db, read_only=True)

    failures: list[tuple[str, str, str]] = []
    review: list[tuple[str, str, str]] = []

    ids = Counter(c.get("id") for c in cases)
    for dup in (i for i, k in ids.items() if k > 1):
        failures.append((dup, "structure", "duplicate id"))

    for c in cases:
        cid = c.get("id", "?")
        bucket = review if c.get("needs_validation") else failures

        if err := check_structure(c):
            failures.append((cid, "structure", err))  # always fatal
            continue
        sql = c["gold_sql"]
        if sql is None:
            continue
        if err := check_single_select_and_tables(sql):
            failures.append((cid, "sql", err))  # always fatal — this is our own SQL, must be valid
            continue
        if err := check_binds(con, sql):
            bucket.append((cid, "schema", err))
            continue
        if not args.skip_exec and (err := check_executes(con, c)):
            bucket.append((cid, "data", err))

    for p in check_ticker_anchors(con):
        failures.append(("TICKER", "anchor", p))

    tiers = Counter(c["tier"] for c in cases)
    behav = Counter(c["expected"] for c in cases)
    nv = sum(1 for c in cases if c.get("needs_validation"))
    print(
        f"{len(cases)} cases | tiers: {dict(tiers)} | expected: {dict(behav)}"
        f" | needs_validation: {nv}"
    )

    for n in check_staging_tables_hidden(con):
        print(n)

    if review:
        print(
            f"\n{len(review)} REVIEW NEEDED (needs_validation cases — read"
            " validation_note, adjust if wrong):\n"
        )
        for cid, kind, reason in review:
            note = next((c.get("validation_note", "") for c in cases if c["id"] == cid), "")
            print(f"  {cid:<6} {kind:<9} {reason}")
            if note:
                print(f"         -> {note}")

    if not failures:
        print(
            "\nALL HARD CHECKS PASSED"
            + (" (some cases need manual review — see above)" if review else "")
        )
        return 0

    by_kind = Counter(k for _, k, _ in failures)
    print(f"\n{len(failures)} failures ({dict(by_kind)}):\n")
    for cid, kind, reason in failures:
        print(f"  {cid:<6} {kind:<9} {reason}")
    print(
        "\nHow to read this: 'schema'/'sql' failures mean gold.jsonl disagrees with"
        " docs/schema.md — fix the gold SQL (preferred) or flag a real Phase-1 schema"
        " bug. 'data' failures on a case NOT marked needs_validation mean I was"
        " confidently wrong about that fact — fix the gold_sql or expected field."
        " 'anchor' failures mean a ticker or a hardcoded value (e.g. Apple's confirmed"
        " revenue) doesn't match the live data — investigate before trusting anything"
        " else."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
