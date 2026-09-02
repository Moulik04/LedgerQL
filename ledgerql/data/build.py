"""Orchestrates the Phase 1 data pipeline: download -> ingest -> mart.

Entrypoint for `make data` (see Makefile, `python -m ledgerql.data.build`).
"""

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from ledgerql.data.download import QUARTERS, download_all
from ledgerql.data.ingest import ensure_staging_tables, ingest_all
from ledgerql.data.mart import build_mart
from ledgerql.data.sp500 import load_sp500, sp500_ciks

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_CACHE_DIR = REPO_ROOT / "data" / "raw"


def run(db_path: Path) -> None:
    companies = load_sp500()
    ciks = sp500_ciks(companies)
    print(f"Loaded {len(companies)} S&P 500 companies ({len(ciks)} unique CIKs)")

    zip_paths = download_all(QUARTERS, RAW_CACHE_DIR)
    print(f"Cached {len(zip_paths)} quarterly zips under {RAW_CACHE_DIR}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        ensure_staging_tables(con)
        stats = ingest_all(con, list(zip(QUARTERS, zip_paths, strict=True)), ciks)
        total_skipped = sum(s.skipped_rows for s in stats)
        for s in stats:
            print(
                f"  {s.quarter}: sub={s.sub_rows} num={s.num_rows} "
                f"tag={s.tag_rows} skipped={s.skipped_rows}"
            )
        if total_skipped:
            print(f"WARNING: {total_skipped} malformed rows skipped across all quarters")

        build_mart(con, companies)
        n_facts = con.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0]
        n_filings = con.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        print(f"Mart built: {n_filings} filings, {n_facts} financial facts")
    finally:
        con.close()


if __name__ == "__main__":
    load_dotenv()
    default_path = REPO_ROOT / "data" / "ledgerql.duckdb"
    db_path = Path(os.environ.get("LEDGERQL_DB_PATH", str(default_path)))
    run(db_path)
