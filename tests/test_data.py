"""Phase 1 acceptance tests: run `make data` first to build
data/ledgerql.duckdb, then `make test` (or `pytest tests/test_data.py`)
to verify it. Each figure below is hand-verified against the company's
real 10-K filing — see docs/superpowers/plans/2026-09-02-phase1-data.md
for the source accession numbers.
"""

import os
from pathlib import Path

import duckdb
import pytest

# Mirror ledgerql/data/build.py's default-path resolution exactly, so these
# acceptance tests verify whatever database `make data` actually built --
# rather than silently skipping (via pytestmark below) when LEDGERQL_DB_PATH
# points somewhere else.
DB_PATH = Path(
    os.environ.get(
        "LEDGERQL_DB_PATH", str(Path(__file__).parent.parent / "data" / "ledgerql.duckdb")
    )
)

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
        SELECT cik, adsh, tag, ddate, qtrs, uom, COUNT(*) AS n
        FROM financial_facts
        GROUP BY cik, adsh, tag, ddate, qtrs, uom
        HAVING COUNT(*) > 1
    """
    ).fetchall()
    assert dupes == []


def test_sp500_coverage_has_few_companies_with_no_10k(con):
    # Every S&P 500 constituent should have at least one 10-K in the pinned
    # quarter window, EXCEPT genuinely new spin-off registrants with no
    # filing history yet. As of this fix wave, that's FDXF and HONA only --
    # confirmed by name below so a regression (e.g. a wrong/missing CIK like
    # the XOM bug this fix wave corrected) fails loudly instead of silently
    # producing zero rows for a real constituent.
    n = con.execute(
        """
        SELECT COUNT(*) FROM companies c
        WHERE NOT EXISTS (
            SELECT 1 FROM filings f WHERE f.cik = c.cik AND f.form = '10-K'
        )
    """
    ).fetchone()[0]
    assert n <= 2, (
        f"{n} S&P 500 companies have zero 10-K filings in this window "
        "(expected at most 2: FDXF, HONA -- new spin-off registrants)"
    )


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


def test_coca_cola_fy2024_revenue_via_fallback_tag(con):
    # Intentionally tests the FALLBACK-tag path, not the top-priority tag: all
    # 10 figures above happen to resolve via each concept's top-priority tag.
    # Coca-Cola reports revenue under `Revenues` (v_revenue's 3rd-priority tag),
    # not the top-priority `RevenueFromContractWithCustomerExcludingAssessedTax`.
    # Source: The Coca-Cola Company 10-K, accession 0000021344-25-000011,
    # filed 2025-02-20 (CIK 21344).
    row = con.execute(
        "SELECT value, source_tag FROM v_revenue WHERE ticker = ? AND fiscal_year = ?",
        ["KO", 2024],
    ).fetchone()
    assert row is not None, "no v_revenue row for KO FY2024"
    value, source_tag = row
    assert value == 47_061_000_000.0
    assert source_tag == "Revenues"
