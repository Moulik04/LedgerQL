"""Build the small eval fixture DB used by CI from the real mart.

The real data/ledgerql.duckdb is ~185MB, almost entirely the raw SEC
staging tables (stg_sub/stg_num/stg_tag) that no gold query ever touches
(evals/validate_gold.py's ALLOWED_TABLES enforces this). The mart itself
-- companies, filings, financial_facts, and the four concept views -- is
tiny and is exactly what evals/gold.jsonl's 103 cases run against. This
copies just that mart, unfiltered, into tests/fixtures/eval_fixture.duckdb
so CI gets the real data (every company, every fact) without the staging
bulk.

Run after any Phase 1 data rebuild:

    uv run python scripts/build_eval_fixture.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

MART_TABLES = ["companies", "filings", "financial_facts"]
VIEWS = ["v_revenue", "v_net_income", "v_total_assets", "v_cash"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/ledgerql.duckdb")
    ap.add_argument("--out", default="tests/fixtures/eval_fixture.duckdb")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.unlink(missing_ok=True)

    con = duckdb.connect(args.src, read_only=True)
    escaped = str(out_path).replace("'", "''")
    con.execute(f"ATTACH '{escaped}' AS fx (READ_ONLY FALSE)")

    for t in MART_TABLES:
        con.execute(f"CREATE TABLE fx.{t} AS SELECT * FROM {t}")

    for v in VIEWS:
        (view_sql,) = con.execute(
            "SELECT sql FROM duckdb_views() WHERE view_name = ?", [v]
        ).fetchone()
        # view_sql is `CREATE VIEW v_x AS SELECT ...` against the source
        # catalog's tables; re-run it inside fx so it binds to fx's own
        # freshly-copied tables instead of qualifying back to the source.
        con.execute(f"CREATE VIEW fx.{v} AS " + view_sql.split(" AS ", 1)[1])

    con.execute("DETACH fx")
    con.close()

    size_mb = out_path.stat().st_size / 1_000_000
    print(f"wrote {out_path} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
