# Phase 1 — Data: Design Spec

Status: approved, pending implementation plan.
Scope: LEDGERQL_MASTER_PROMPT.md Phase 1 acceptance criteria only (EDGAR
ingestion, analyst schema, `docs/schema.md`, 10 sanity queries in
`tests/test_data.py`, `make data` builds from scratch).

## 1. Data scope

- **Source:** SEC Financial Statement Data Sets (`sub.txt`, `num.txt`,
  `tag.txt` per quarterly zip from sec.gov).
- **Companies:** filtered to S&P 500 constituents only, not the full
  ~6,000-filer universe. Filtering happens during ingest (staging tables
  never hold non-S&P-500 rows), so the working dataset stays small.
- **Quarters:** the 8 most recently available quarters as of
  implementation time (two full fiscal years). Gives headroom for
  year-over-year comparison questions later in the eval set.
- **S&P 500 list:** a static file, `data/sp500_constituents.csv`
  (ticker, company name, CIK), pinned as of the date it's generated and
  checked into git. No runtime dependency on a third-party list; refreshed
  by hand if it goes stale. Sourced once from a public constituent list
  during implementation and cited in the file itself.

## 2. Database layering

Two layers in `data/ledgerql.duckdb`:

**Staging** — near-raw SEC data, filtered to S&P 500 CIKs, columns
mirror the source `.txt` files:
- `stg_sub` (submissions: adsh, cik, name, sic, form, fiscal year/period,
  filed date, ...)
- `stg_num` (numeric facts: adsh, tag, version, coreg, ddate, qtrs, uom,
  value, footnote)
- `stg_tag` (tag metadata: tag, version, datatype, crdr, label, doc)

**Analyst mart** — built from staging via SQL transforms, the only layer
`docs/schema.md` documents and the only layer SQL generation ever sees:
- `companies` (cik PK, ticker, name, sic, ...)
- `filings` (adsh PK, cik FK, form, fiscal_year, fiscal_period,
  period_end_date, filed_date)
- `financial_facts` (long format: cik, adsh, tag, ddate, qtrs, uom, value
  — one row per reported fact)
- Materialized views: `v_revenue`, `v_net_income`, `v_total_assets`,
  `v_cash` — each resolves to (cik, ticker, name, fiscal_year,
  fiscal_period, period_end_date, value, uom, source_tag).

Rationale: when a figure looks wrong, staging lets you check whether the
problem is in SEC's raw data, the mart transform, or a view's tag
mapping — without re-downloading or re-parsing anything. Costs nothing
extra in an embedded DuckDB file.

## 3. Components

New `ledgerql/data/` package:

- `sp500.py` — loads `data/sp500_constituents.csv`.
- `download.py` — fetches the 8 target quarterly zips from
  `sec.gov/files/dera/data/financial-statement-data-sets/`, caches under
  `data/raw/` (gitignored), sends SEC's required descriptive `User-Agent`
  header.
- `ingest.py` — streams each quarter's `sub.txt`/`num.txt`/`tag.txt`,
  filters to S&P 500 CIKs, loads into staging tables. Appends one quarter
  at a time so a partial failure doesn't corrupt prior quarters.
- `build_mart.py` — SQL transforms staging → `companies`, `filings`,
  `financial_facts`, and the 4 concept views.
- `cli.py` — orchestrates download → ingest → build_mart for `make data`.
  Idempotent: safe to re-run, rebuilds the mart every time, only
  re-downloads quarter zips missing from the cache.

## 4. Tag mapping (concept views)

Companies use different XBRL tags for the same concept (e.g. revenue
might be reported under `Revenues`,
`RevenueFromContractWithCustomerExcludingAssessedTax`, or
`SalesRevenueNet`). Each concept view resolves this with `COALESCE`
across a small ranked list of acceptable tags per concept. The exact
ranked lists are finalized during implementation and documented
explicitly in `docs/schema.md` — never a hidden mapping.

## 5. Error handling

- A company/quarter with no matching tag for a concept is simply absent
  from that view — `docs/schema.md` states explicitly that absence means
  "not reported under a known tag," never "zero."
- Malformed rows in SEC's source files are logged and skipped, not
  silently dropped; `make data` prints a skipped-row count at the end.

## 6. Testing

`tests/test_data.py`:
1. **Structural sanity** — staging and mart tables are non-empty,
   `financial_facts` has no duplicate `(cik, adsh, tag, ddate, qtrs)`
   rows, expected column types.
2. **10 hand-verified figures** — for well-known S&P 500 companies
   (e.g. Apple, Microsoft, Amazon, JPMorgan), assert a concept view
   matches the real reported number for a specific fiscal period. Each
   assertion cites company, fiscal period, and source in the test itself
   — verified against the real filing during implementation, not
   approximated.

Sanity checks live only in pytest, not in `make data` itself — `make
data`'s job is just to build the database; `make test` is what verifies
correctness. This matches the master prompt's Phase 1 acceptance
criteria, which lists these as two separate conditions.

## 7. Out of scope for this spec

- Anything in `classify.py`, `generate.py`, or later pipeline stages
  (Phase 2+).
- The synthetic bank-ledger schema (Phase 4+, optional).
- BIRD benchmark integration (Phase 5, optional).
