# Schema

The analyst-facing mart in `data/ledgerql.duckdb`. This is the only
layer SQL generation ever sees — the raw staging tables (`stg_sub`,
`stg_num`, `stg_tag`) exist purely for debugging data-quality questions
and are never queried by the pipeline.

**Coverage:** S&P 500 constituents (`data/sp500_constituents.csv`,
pinned snapshot), 8 quarters of SEC filings (2024q3-2026q2), **annual
figures only** (10-K filings, fiscal-year period). Quarterly (10-Q)
granularity is a Phase 2+ extension.

## companies

One row per S&P 500 constituent.

| Column | Type | Example |
|---|---|---|
| cik | INTEGER (PK) | 320193 |
| ticker | VARCHAR | AAPL |
| name | VARCHAR | Apple Inc. |
| gics_sector | VARCHAR | Information Technology |

**Note on dual-class shares:** A handful of S&P 500 constituents issue multiple share classes with separate stock tickers but a single SEC CIK (e.g., GOOGL/GOOG, FOXA/FOX, NWSA/NWS). Since `companies`, `filings`, and `financial_facts` are all CIK-grained (one row per actual SEC filer, not per ticker), only one canonical ticker appears in this table: the first-listed ticker for that CIK from `data/sp500_constituents.csv` (the Class A share in all current cases). This means querying for the subordinate class ticker (e.g., GOOG) will find no `companies` row — only the canonical ticker (e.g., GOOGL) will match.

## filings

One row per SEC submission (any form type) by an S&P 500 company in the
covered quarters — not just 10-Ks; useful for "how many filings has X
made" style questions even though `financial_facts` only draws from 10-Ks.

| Column | Type | Example |
|---|---|---|
| adsh | VARCHAR (PK) | 0000320193-24-000123 |
| cik | INTEGER (FK -> companies.cik) | 320193 |
| form | VARCHAR | 10-K |
| fiscal_year | INTEGER | 2024 |
| fiscal_period | VARCHAR | FY |
| period_end_date | DATE | 2024-09-30 |
| filed_date | DATE | 2024-11-01 |

## financial_facts

Long format: one row per reported numeric fact from a 10-K's primary
financial statements, restricted to the filing's own fiscal-year period
(prior-year comparatives shown in the same filing are excluded) and to
consolidated, non-dimensional values (`segments = ''`, `coreg = ''` in
the source data — no product-line or geographic breakdowns).

| Column | Type | Example |
|---|---|---|
| cik | INTEGER | 320193 |
| adsh | VARCHAR | 0000320193-24-000123 |
| tag | VARCHAR | RevenueFromContractWithCustomerExcludingAssessedTax |
| ddate | DATE | 2024-09-30 |
| qtrs | INTEGER | 4 (full fiscal year) or 0 (instant, e.g. balance sheet) |
| uom | VARCHAR | USD |
| value | DOUBLE | 391035000000.0 |

**A tag simply absent for a company/year means "not reported under a
known tag" — never treat absence as zero.**

## Concept views

Convenience projections over `financial_facts` for the four headline
concepts. Each resolves cross-company tag variation (companies tag the
same concept differently) by picking the highest-priority tag present,
per company per fiscal year:

| View | Concept | Tag priority (first match wins) | `qtrs` |
|---|---|---|---|
| `v_revenue` | Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `Revenues`, `SalesRevenueNet` | 4 |
| `v_net_income` | Net income | `NetIncomeLoss`, `ProfitLoss` | 4 |
| `v_total_assets` | Total assets | `Assets` | 0 |
| `v_cash` | Cash | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` | 0 |

Columns: `cik, ticker, name, fiscal_year, fiscal_period, period_end_date,
value, uom, source_tag` (`source_tag` records which tag in the priority
list actually matched, for auditability).

**Known gap:** bank holding companies (e.g. JPMorgan) generally don't
file a single `Revenues`-style tag, so they may be absent from
`v_revenue` even though they appear in `v_net_income`/`v_total_assets`.
This is the "absence, not zero" policy working as intended, not a bug.

Example — Apple's revenue across the two fiscal years in the pinned
dataset:

```sql
SELECT ticker, fiscal_year, value FROM v_revenue WHERE ticker = 'AAPL' ORDER BY fiscal_year;
-- AAPL, 2024, 391035000000.0
-- AAPL, 2025, 416161000000.0
```
