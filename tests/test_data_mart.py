# ruff: noqa: E501
import duckdb

from ledgerql.data.ingest import ensure_staging_tables
from ledgerql.data.mart import build_mart
from ledgerql.data.sp500 import SP500Company

COMPANIES = [SP500Company("AAPL", "Apple Inc.", 320193, "Information Technology")]


def _seed_staging(con: duckdb.DuckDBPyConnection) -> None:
    ensure_staging_tables(con)
    con.execute(
        """
        INSERT INTO stg_sub VALUES
        ('0000320193-24-000123', 320193, 'APPLE INC', '3571', '10-K', '20240930', 2024, 'FY', '20241101', '2024q4')
    """
    )
    # Three years of revenue comparatives in the same filing, plus a
    # dimensional (segment) row and a fallback-tag scenario, mirroring
    # real 10-K num.txt content.
    con.execute(
        """
        INSERT INTO stg_num VALUES
        ('0000320193-24-000123', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2024', '20220930', 4, 'USD', '', '', 394328000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2024', '20230930', 4, 'USD', '', '', 383285000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2024', '20240930', 4, 'USD', '', '', 391035000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2024', '20240930', 4, 'USD', 'ProductLine=iPhone', '', 200000000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'NetIncomeLoss', 'us-gaap/2024', '20240930', 4, 'USD', '', '', 93736000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'Assets', 'us-gaap/2024', '20240930', 0, 'USD', '', '', 364980000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'Assets', 'us-gaap/2024', '20230930', 0, 'USD', '', '', 352583000000.0, '', 320193, '2024q4'),
        ('0000320193-24-000123', 'CashAndCashEquivalentsAtCarryingValue', 'us-gaap/2024', '20240930', 0, 'USD', '', '', 29943000000.0, '', 320193, '2024q4')
    """
    )


def test_build_mart_creates_companies_and_filings():
    con = duckdb.connect(":memory:")
    _seed_staging(con)
    build_mart(con, COMPANIES)

    companies = con.execute("SELECT cik, ticker, name, gics_sector FROM companies").fetchall()
    assert companies == [(320193, "AAPL", "Apple Inc.", "Information Technology")]

    filings = con.execute(
        "SELECT adsh, cik, form, fiscal_year, fiscal_period FROM filings"
    ).fetchall()
    assert filings == [("0000320193-24-000123", 320193, "10-K", 2024, "FY")]


def test_v_revenue_isolates_own_period_and_excludes_segments():
    con = duckdb.connect(":memory:")
    _seed_staging(con)
    build_mart(con, COMPANIES)

    rows = con.execute("SELECT ticker, fiscal_year, value, source_tag FROM v_revenue").fetchall()
    assert rows == [
        (
            "AAPL",
            2024,
            391035000000.0,
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        )
    ]


def test_v_net_income_v_total_assets_v_cash():
    con = duckdb.connect(":memory:")
    _seed_staging(con)
    build_mart(con, COMPANIES)

    assert con.execute("SELECT value FROM v_net_income").fetchall() == [(93736000000.0,)]
    assert con.execute("SELECT value FROM v_total_assets").fetchall() == [(364980000000.0,)]
    assert con.execute("SELECT value FROM v_cash").fetchall() == [(29943000000.0,)]


def test_financial_facts_excludes_dimensional_rows():
    con = duckdb.connect(":memory:")
    _seed_staging(con)
    build_mart(con, COMPANIES)

    tags = con.execute(
        "SELECT DISTINCT tag FROM financial_facts WHERE ddate = DATE '2024-09-30' ORDER BY tag"
    ).fetchall()
    assert ("RevenueFromContractWithCustomerExcludingAssessedTax",) in tags
    all_tags = [t for (t,) in tags]
    assert not any(
        "Product" in t for t in all_tags
    ), "dimensional/segment rows must not leak into financial_facts"
