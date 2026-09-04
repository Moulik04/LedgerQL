# Schema Expansion — Design Spec

Status: approved, pending implementation plan.
Scope: reconcile LedgerQL's Phase 1 analyst mart with `evals/schema_contract.md`
(the schema a 102-case gold eval set, `evals/gold.jsonl`, was written
against), per the master prompt's checkpoint rule on changing the schema
after Phase 1 — the user has explicitly approved this change.

## 1. Why

Phase 1 shipped a narrower mart than this eval set needs: 4 concept views
(`v_revenue`, `v_net_income`, `v_total_assets`, `v_cash`) over annual
(10-K only) data across a pinned 8-quarter window. `schema_contract.md`
specifies a wider `statement_metrics` view (14 metrics, annual *and*
quarterly), richer `companies`/`filings` tables, and a `tags` table — none
of which exist today. Every one of the 102 gold cases queries
`statement_metrics`, so none of them currently bind against the real
database.

## 2. Quarter window expansion

Current: `2024q3`–`2026q2` (8 quarters). New: **`2023q1`–`2026q2`** (14
quarters, 6 new zips: `2023q1`, `2023q2`, `2023q3`, `2023q4`, `2024q1`,
`2024q2`).

Rationale: `gold.jsonl` has YoY/CAGR questions needing each company's own
FY2022 and FY2023 10-K as a *primary* filing (not a comparative figure
embedded in a later filing, which the mart's `ddate = period` filter
deliberately excludes — see Phase 1's `DECISIONS.md`). Given fiscal-year-end
varies by company, the earliest 10-K filing date for FY2022 in this gold
set is Tesla's (December FYE, FY2022 10-K filed ~Feb 2023, in the `2023q1`
zip). `2023q1` through `2024q2` covers every fiscal-year-end convention's
FY2022/FY2023 10-K in the S&P 500. One gold case references FY2019 — this
is intentionally out of range (a no-data test case, `expected: ABSTAIN`,
`reason_code: NO_DATA`) and does not extend the window further.

The 6 new zips get downloaded and cached exactly like the existing 8 — no
change to `download.py`'s caching mechanism, only its `QUARTERS` constant.

## 3. Table changes

### `companies`

Adds `sic_description`, `state_of_incorporation`, `fiscal_year_end`.

- `state_of_incorporation` and `fiscal_year_end` map to `sub.txt`'s real
  `stprinc` and `fye` columns — present in every SEC quarterly zip, not
  currently captured by `stg_sub`. Adding them is a staging DDL change,
  populated by the same ingest pass (no new download).
- `sic_description` has no source in Phase 1's data. New pinned reference
  file `data/sic_codes.csv` (sic code → description), fetched once via a
  new `scripts/fetch_sic_codes.py` from SEC's public SIC code list — same
  pattern as `scripts/fetch_sp500.py`. `companies.sic_description` is a
  lookup join against this file at mart-build time, not stored per-row in
  staging.

### `filings`

Renames `period_end_date` → `period_end` (matching `schema_contract.md`).
`fiscal_period` already holds whatever SEC's raw `fp` value is (`FY`,
`Q1`, `Q2`, `Q3` — SEC never files a `Q4`); no code change needed there,
since the *restriction* to `fp='FY'` lived in `mart.py`, not in `filings`
itself. `filings` already includes every form type, so no change needed
to include 10-Qs at this table.

### `financial_facts`

- Drops the `form='10-K' AND fp='FY'` restriction — now `form IN ('10-K',
  '10-Q')`, still excluding `10-K/A` and `10-KT` (unchanged from Phase 1's
  decision to only trust primary, non-amended, non-transition filings).
- Renames `ddate`→`period_end`, `qtrs`→`quarters`, `uom`→`unit` (matching
  `schema_contract.md`).
- Adds `fiscal_year`, `fiscal_period` (copied from the owning filing, per
  `schema_contract.md` — denormalized for query convenience).
- Adds `is_custom` (`BOOLEAN`), sourced by joining `tag` to `stg_tag.custom`
  (already staged in Phase 1, never previously surfaced past staging).

### `tags` (new)

`tag` (PK), `label`, `description`, `is_custom` — a direct projection of
`stg_tag`, finally exposed at the mart layer. `label`/`description` come
from `stg_tag.tlabel`/`stg_tag.doc`.

`stg_tag` is staged per-quarter (a tag name can legitimately appear in
more than one quarter's `tag.txt`, since it's re-published every quarter
regardless of whether it changed), but `tags.tag` is a single-column PK —
one row per tag name, not per tag-per-quarter. Resolve by keeping the row
from the most recent quarter (`stg_tag.quarter`) for each tag name; a
tag's `custom`/`label`/`description` are effectively invariant across
quarters in practice, so this is a deterministic tie-break, not a
meaningful data choice.

### `statement_metrics` (new, replaces the 4 concept views)

One row per **reported or derived** period — see §4 for what "derived"
means. Columns: `adsh`, `cik`, `company_name`, `ticker`, `form`,
`fiscal_year`, `fiscal_period`, `period_end`, plus the 14 metrics from
`schema_contract.md` (`revenue`, `cost_of_revenue`, `gross_profit`,
`operating_income`, `net_income`, `eps_diluted`, `total_assets`,
`total_liabilities`, `stockholders_equity`, `cash`, `long_term_debt`,
`operating_cash_flow`, `capex`, `shares_outstanding`), plus `is_derived`
(§4).

**Natural key: `(cik, fiscal_year, fiscal_period)`, not `adsh`.** A real,
filed period's `adsh` is unique per `(cik, fiscal_year, fiscal_period)`
already, so this is consistent with `schema_contract.md`'s "one row per
filing" framing for every row *except* derived Q4 rows, which have no
filing of their own — see §4. This is a deliberate, documented deviation
from `schema_contract.md`'s literal "PK: adsh" framing, made necessary by
adding the derived-Q4 concept the user requested; `docs/schema.md` states
this explicitly so it's never ambiguous which column is actually unique.

Each metric is resolved via the same tag-priority pattern Phase 1 already
built and validated (`QUALIFY ROW_NUMBER() OVER (PARTITION BY ... ORDER BY
CASE tag ...) = 1`), generalized from "one CTE per concept, joined to
`companies`/`filings`" to "14 CTEs, one per metric, partitioned by
`(cik, fiscal_year, fiscal_period, ddate)` [reusing Phase 1's `ddate`
tiebreaker fix from the final Phase 1 review], LEFT JOINed together into
one wide row per filing." Tag priority lists are taken verbatim from
`schema_contract.md`'s "derived from (first non-null in order)" column —
already fully specified there, not re-derived here.

Instant metrics (`total_assets`, `total_liabilities`, `stockholders_equity`,
`cash`, `long_term_debt`, `shares_outstanding`) use `quarters = 0`. Flow
metrics (`revenue`, `cost_of_revenue`, `gross_profit`, `operating_income`,
`net_income`, `operating_cash_flow`, `capex`) use `quarters = 4` on `FY`
rows and `quarters = 1` on `Q1`–`Q3` rows. `eps_diluted` is per-share
(`unit = 'USD/shares'`), duration-based like the flow metrics.
`gross_profit` falls back to `revenue - cost_of_revenue` when the
`GrossProfit` tag itself is absent but both operands are present (per
`schema_contract.md`).

## 4. Q4 derivation and the `is_derived` flag

SEC never files a Q4 report — the annual 10-K covers the full year
instead. For each `(cik, fiscal_year)` where `FY`, `Q1`, `Q2`, and `Q3`
rows are **all** present in `statement_metrics`, synthesize a `Q4` row:

- Flow metrics: `FY − (Q1 + Q2 + Q3)`, computed only when all four values
  (FY and all three quarters) are non-NULL for that specific metric — a
  metric missing from even one quarter means that metric stays NULL on the
  derived Q4 row (not silently computed from partial data), even if other
  metrics on the same row do have all four quarters.
- Instant metrics: copied directly from the `FY` row's own values (fiscal
  year end *is* Q4's end — no arithmetic needed, no double-derivation
  risk).
- `eps_diluted`: NOT derived (per-share figures don't sum meaningfully
  across quarters when share count changes) — stays NULL on derived Q4
  rows.
- `adsh`: set to the **source `FY` filing's** `adsh`, so a derived row is
  always traceable to the annual filing it came from — never a synthetic
  accession number.
- `is_derived`: `TRUE` on every synthesized Q4 row, `FALSE` on every row
  that corresponds to a real SEC filing. This is the flag the user asked
  for — it's what lets a consumer (or the eval harness) distinguish "SEC
  actually reported this" from "we computed this by subtraction."

If any of `FY`/`Q1`/`Q2`/`Q3` is missing for a `(cik, fiscal_year)`, no Q4
row is synthesized for that company/year at all — never a partially-derived
row.

## 5. Retiring the old views

`v_revenue`, `v_net_income`, `v_total_assets`, `v_cash` are dropped.
`statement_metrics` is a strict superset of what they provided (same 4
metrics, annual and quarterly, plus 10 more) — keeping both would be two
ways to get the same number with real risk of drifting out of sync, and
nothing in `gold.jsonl` queries the old views.

## 6. Documentation and acceptance

- `docs/schema.md` gets a full rewrite reflecting every table/column above,
  written in the same "known real-world traps" style `schema_contract.md`
  already uses (fiscal ≠ calendar year, two Ford registrants, negative
  equity, `is_derived` semantics, etc.) — this is the file injected into
  future SQL-generation prompts, so precision matters here specifically.
- `Makefile` gets a new `eval-validate` target running
  `python evals/validate_gold.py --db data/ledgerql.duckdb`.
- Phase 1's 10 hand-verified figures (Apple/Amazon/Microsoft) stay as
  `tests/test_data.py` assertions, now querying `statement_metrics` instead
  of the retired views — still real, independently-verified regression
  protection.
- `evals/validate_gold.py` becomes an *additional* acceptance gate per the
  user's original instruction: "do not record the Phase 2 baseline until
  it prints ALL CHECKS PASSED." Any `schema` failures it reports get fixed
  by editing `gold.jsonl`/`schema_contract.md` to match the real
  `docs/schema.md` (never the other way — `docs/schema.md` reflects the
  real, live database); any `data` failures get fixed in the loader.
- Once `docs/schema.md` is rewritten and the real database is rebuilt, the
  user does their own reconciliation pass on `gold.jsonl` — several
  currently-`ABSTAIN` cases (quarterly-data cases, SIC-based cases) are
  expected to flip to `ANSWER` now that the underlying data exists. This
  spec's implementation plan stops at "database built, schema documented,
  `validate_gold.py` runnable" — the gold-set reconciliation itself is the
  user's own pass, not part of this plan.

## 7. Out of scope for this spec

- Anything in `classify.py`, `generate.py`, or later pipeline stages
  (Phase 2+ proper — SQL generation, execution, answer synthesis).
- Reconciling `gold.jsonl`'s actual case-by-case `expected`/`gold_sql`
  content against the new schema (the user's own pass, per §6).
- The synthetic bank-ledger schema (Phase 4+, optional, unrelated).
