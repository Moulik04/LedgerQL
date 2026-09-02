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


def test_tag_priority_resolution_revenue():
    """Verify that when multiple tags for same concept exist in same partition,
    the highest-priority tag is selected.
    """
    con = duckdb.connect(":memory:")
    ensure_staging_tables(con)
    # Add two filings: one with high-priority tag, one with fallback tag
    con.execute(
        """
        INSERT INTO stg_sub VALUES
        ('0000320193-25-000001', 320193, 'APPLE INC', '3571', '10-K', '20250930', 2025, 'FY', '20251101', '2025q4'),
        ('0000320193-26-000002', 320193, 'APPLE INC', '3571', '10-K', '20260930', 2026, 'FY', '20261101', '2026q4')
    """
    )
    # FY2025: high-priority tag RevenueFromContractWithCustomerExcludingAssessedTax
    # FY2026: both high-priority and lower-priority Revenues tag (same cik/fiscal_year)
    # to test that QUALIFY picks the one with higher priority
    con.execute(
        """
        INSERT INTO stg_num VALUES
        ('0000320193-25-000001', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2025', '20250930', 4, 'USD', '', '', 400000000000.0, '', 320193, '2025q4'),
        ('0000320193-26-000002', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'us-gaap/2026', '20260930', 4, 'USD', '', '', 450000000000.0, '', 320193, '2026q4'),
        ('0000320193-26-000002', 'Revenues', 'us-gaap/2026', '20260930', 4, 'USD', '', '', 500000000000.0, '', 320193, '2026q4')
    """
    )
    build_mart(con, COMPANIES)

    rows = con.execute(
        "SELECT fiscal_year, value, source_tag FROM v_revenue ORDER BY fiscal_year"
    ).fetchall()
    # FY2025: should pick RevenueFromContractWithCustomerExcludingAssessedTax (only option)
    # FY2026: should pick RevenueFromContractWithCustomerExcludingAssessedTax (higher priority)
    #         and use its value 450B, NOT the fallback Revenues value of 500B
    assert len(rows) == 2
    assert rows[0] == (
        2025,
        400000000000.0,
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert rows[1] == (
        2026,
        450000000000.0,
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )


def test_tag_priority_resolution_net_income():
    """Verify tag priority for net_income concept with competing tags."""
    con = duckdb.connect(":memory:")
    ensure_staging_tables(con)
    con.execute(
        """
        INSERT INTO stg_sub VALUES
        ('0000320193-27-000003', 320193, 'APPLE INC', '3571', '10-K', '20270930', 2027, 'FY', '20271101', '2027q4')
    """
    )
    # NetIncomeLoss is higher priority than ProfitLoss
    # Seed both tags for same cik/fiscal_year to test priority
    con.execute(
        """
        INSERT INTO stg_num VALUES
        ('0000320193-27-000003', 'NetIncomeLoss', 'us-gaap/2027', '20270930', 4, 'USD', '', '', 95000000000.0, '', 320193, '2027q4'),
        ('0000320193-27-000003', 'ProfitLoss', 'us-gaap/2027', '20270930', 4, 'USD', '', '', 100000000000.0, '', 320193, '2027q4')
    """
    )
    build_mart(con, COMPANIES)

    rows = con.execute("SELECT fiscal_year, value, source_tag FROM v_net_income").fetchall()
    # Should pick NetIncomeLoss (higher priority) with value 95B, not ProfitLoss's 100B
    assert len(rows) == 1
    assert rows[0] == (2027, 95000000000.0, "NetIncomeLoss")
