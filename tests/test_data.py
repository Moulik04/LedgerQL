"""Phase 1 acceptance tests: run `make data` first to build
data/ledgerql.duckdb, then `make test` (or `pytest tests/test_data.py`)
to verify it. Each figure below is hand-verified against the company's
real 10-K filing — see docs/superpowers/plans/2026-09-02-phase1-data.md
for the source accession numbers.
"""

from pathlib import Path

import duckdb
import pytest

DB_PATH = Path(__file__).parent.parent / "data" / "ledgerql.duckdb"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="data/ledgerql.duckdb not found — run `make data` first",
)


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


# --- Structural sanity -------------------------------------------------


def test_core_tables_are_non_empty(con):
    for table in ["companies", "filings", "financial_facts"]:
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count > 0, f"{table} is empty"


def test_financial_facts_has_no_duplicate_keys(con):
    dupes = con.execute(
        """
        SELECT cik, adsh, tag, ddate, qtrs, COUNT(*) AS n
        FROM financial_facts
        GROUP BY cik, adsh, tag, ddate, qtrs
        HAVING COUNT(*) > 1
    """
    ).fetchall()
    assert dupes == []


def test_concept_views_have_expected_columns(con):
    for view in ["v_revenue", "v_net_income", "v_total_assets", "v_cash"]:
        columns = {c[0] for c in con.execute(f"DESCRIBE {view}").fetchall()}
        assert columns == {
            "cik",
            "ticker",
            "name",
            "fiscal_year",
            "fiscal_period",
            "period_end_date",
            "value",
            "uom",
            "source_tag",
        }


# --- 10 hand-verified figures -------------------------------------------
# Company, fiscal year, concept, value (USD), source: SEC accession number.


def _value(con, view, ticker, fiscal_year):
    row = con.execute(
        f"SELECT value FROM {view} WHERE ticker = ? AND fiscal_year = ?",
        [ticker, fiscal_year],
    ).fetchone()
    assert row is not None, f"no {view} row for {ticker} FY{fiscal_year}"
    return row[0]


def test_apple_fy2024_revenue(con):
    # Source: Apple 10-K, accession 0000320193-24-000123, filed 2024-11-01.
    assert _value(con, "v_revenue", "AAPL", 2024) == 391_035_000_000.0


def test_apple_fy2024_net_income(con):
    # Source: Apple 10-K, accession 0000320193-24-000123.
    assert _value(con, "v_net_income", "AAPL", 2024) == 93_736_000_000.0


def test_apple_fy2024_total_assets(con):
    # Source: Apple 10-K, accession 0000320193-24-000123.
    assert _value(con, "v_total_assets", "AAPL", 2024) == 364_980_000_000.0


def test_apple_fy2024_cash(con):
    # Source: Apple 10-K, accession 0000320193-24-000123.
    assert _value(con, "v_cash", "AAPL", 2024) == 29_943_000_000.0


def test_apple_fy2025_revenue(con):
    # Source: Apple 10-K, accession 0000320193-25-000079, filed 2025-10-31.
    assert _value(con, "v_revenue", "AAPL", 2025) == 416_161_000_000.0


def test_amazon_fy2024_revenue(con):
    # Source: Amazon.com 10-K, accession 0001018724-25-000004, filed 2025-02-07.
    assert _value(con, "v_revenue", "AMZN", 2024) == 637_959_000_000.0


def test_amazon_fy2024_net_income(con):
    # Source: Amazon.com 10-K, accession 0001018724-25-000004.
    assert _value(con, "v_net_income", "AMZN", 2024) == 59_248_000_000.0


def test_amazon_fy2024_cash(con):
    # Source: Amazon.com 10-K, accession 0001018724-25-000004.
    assert _value(con, "v_cash", "AMZN", 2024) == 78_779_000_000.0


def test_microsoft_fy2025_revenue(con):
    # Source: Microsoft 10-K, accession 0000950170-25-100235, filed 2025-07-30.
    assert _value(con, "v_revenue", "MSFT", 2025) == 281_724_000_000.0


def test_microsoft_fy2025_net_income(con):
    # Source: Microsoft 10-K, accession 0000950170-25-100235.
    assert _value(con, "v_net_income", "MSFT", 2025) == 101_832_000_000.0
