"""Builds the analyst-facing mart (companies/filings/financial_facts +
concept views) from the staging tables. This is the only layer SQL
generation ever sees — see docs/schema.md.

Scope for Phase 1: annual figures only (form='10-K', fp='FY', the
filing's own period). Quarterly (10-Q) views are a natural Phase 2+
extension once discrete-vs-YTD qtrs semantics are handled.
"""

from dataclasses import dataclass

import duckdb

from ledgerql.data.sp500 import SP500Company


@dataclass(frozen=True)
class ConceptSpec:
    tags: list[str]
    qtrs: int  # 0 = instant (balance sheet), 4 = full fiscal year (income/cash flow)


CONCEPTS: dict[str, ConceptSpec] = {
    "revenue": ConceptSpec(
        tags=[
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ],
        qtrs=4,
    ),
    "net_income": ConceptSpec(tags=["NetIncomeLoss", "ProfitLoss"], qtrs=4),
    "total_assets": ConceptSpec(tags=["Assets"], qtrs=0),
    "cash": ConceptSpec(
        tags=[
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
        qtrs=0,
    ),
}

_VIEW_NAMES = {
    "revenue": "v_revenue",
    "net_income": "v_net_income",
    "total_assets": "v_total_assets",
    "cash": "v_cash",
}


def build_mart(con: duckdb.DuckDBPyConnection, companies: list[SP500Company]) -> None:
    _build_companies(con, companies)
    _build_filings(con)
    _build_financial_facts(con)
    for concept, spec in CONCEPTS.items():
        _build_concept_view(con, _VIEW_NAMES[concept], spec)


def _build_companies(con: duckdb.DuckDBPyConnection, companies: list[SP500Company]) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE companies (
            cik INTEGER PRIMARY KEY, ticker VARCHAR, name VARCHAR, gics_sector VARCHAR
        )
    """
    )
    # A handful of S&P 500 constituents are dual-class shares (e.g. GOOGL/GOOG,
    # FOXA/FOX, NWSA/NWS) that share a single CIK -- they're one SEC filer with
    # two tickers. filings/financial_facts are CIK-grained, so companies must
    # be too: keep the first-listed ticker per CIK (the CSV lists Class A
    # before Class B/C) as the canonical row for that filer.
    seen_ciks: set[int] = set()
    deduped = []
    for c in companies:
        if c.cik in seen_ciks:
            continue
        seen_ciks.add(c.cik)
        deduped.append(c)
    con.executemany(
        "INSERT INTO companies VALUES (?, ?, ?, ?)",
        [(c.cik, c.ticker, c.name, c.gics_sector) for c in deduped],
    )


def _build_filings(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE filings AS
        SELECT
            adsh,
            cik,
            form,
            -- fy is blank on some non-10-K forms (8-K, S-4, ...) that don't
            -- carry fiscal-year metadata in real SEC data; TRY_CAST nulls
            -- fiscal_year for those rows instead of failing the whole build.
            TRY_CAST(fy AS INTEGER) AS fiscal_year,
            fp AS fiscal_period,
            strptime(period, '%Y%m%d')::DATE AS period_end_date,
            strptime(filed, '%Y%m%d')::DATE AS filed_date
        FROM stg_sub
    """
    )


def _build_financial_facts(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE financial_facts AS
        SELECT
            -- Use registrant CIK from stg_sub (parsed from sub.txt), not from stg_num.
            -- stg_num.agent_cik is derived from the accession number's leading digits,
            -- which represents the filing agent (often third-party), not the registrant.
            s.cik,
            n.adsh,
            n.tag,
            strptime(n.ddate, '%Y%m%d')::DATE AS ddate,
            n.qtrs,
            n.uom,
            n.value
        FROM stg_num n
        JOIN stg_sub s ON n.adsh = s.adsh
        WHERE s.form = '10-K'
          AND s.fp = 'FY'
          AND n.ddate = s.period
          AND n.segments = ''
          AND n.coreg = ''
    """
    )


def _build_concept_view(con: duckdb.DuckDBPyConnection, view_name: str, spec: ConceptSpec) -> None:
    tag_priority_case = " ".join(
        f"WHEN '{tag}' THEN {i}" for i, tag in enumerate(spec.tags, start=1)
    )
    tag_list = ", ".join(f"'{tag}'" for tag in spec.tags)
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT
            f.cik,
            c.ticker,
            c.name,
            fl.fiscal_year,
            fl.fiscal_period,
            f.ddate AS period_end_date,
            f.value,
            f.uom,
            f.tag AS source_tag
        FROM financial_facts f
        JOIN filings fl ON f.adsh = fl.adsh
        JOIN companies c ON f.cik = c.cik
        WHERE f.qtrs = {spec.qtrs}
          AND f.tag IN ({tag_list})
        -- Partition by (cik, fiscal_year, ddate) rather than just (cik,
        -- fiscal_year): SEC's own fy metadata is occasionally wrong (e.g.
        -- Federal Realty's two distinct 10-Ks -- for periods 2024-12-31 and
        -- 2025-12-31 -- both carry sub.fy='2024' in real SEC data). Including
        -- the real period end date (ddate) keeps genuinely different filings
        -- from being silently collapsed into one row just because SEC mislabeled
        -- their fiscal year the same; it's a no-op for every other company,
        -- since ddate and fiscal_year are 1:1 everywhere else in this dataset.
        -- The ORDER BY below still resolves genuine same-period fallback-tag
        -- competition (e.g. NetIncomeLoss vs ProfitLoss for one real filing)
        -- deterministically: tag priority first, then most-recent period end
        -- date, then most-recently filed, as the final tiebreakers.
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY f.cik, fl.fiscal_year, f.ddate
            ORDER BY CASE f.tag {tag_priority_case} END,
                     fl.period_end_date DESC,
                     fl.filed_date DESC
        ) = 1
    """
    )
