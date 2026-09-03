# Decisions

A running log of non-obvious design choices. Format: context → options → decision → consequence.

---

## 2026-09-02 — Package/dependency manager

**Context:** Need a Python 3.11+ environment manager with a lockfile, reproducible via `make setup` on a fresh clone.

**Options:**
- `pip` + `requirements.txt` — ubiquitous, no lockfile guarantees without extra tooling.
- `poetry` — mature, but slower resolver and heavier for a small project.
- `uv` — fast, single static binary, native lockfile, `uv run` pins the interpreter per-project.

**Decision:** `uv`, pinned to Python 3.12 for the project venv (system Python is 3.14, ahead of what some data/ML packages have wheels for yet).

**Consequence:** Contributors need `uv` installed (`brew install uv`) before `make setup`. Everything else is one command.

---

## 2026-09-02 — Repo scaffold before Phase 1 data work

**Context:** Phase 0 acceptance criteria: repo layout, `pyproject.toml`, `Makefile`, pre-commit, pytest skeleton, `DECISIONS.md`, `README.md` stub, `.env.example`, MIT license, `make setup && make test` passing.

**Decision:** Module files under `ledgerql/` are created as typed stubs (docstring + `NotImplementedError` or pass) so imports resolve and the pytest skeleton is meaningful, without pre-building Phase 1+ logic.

**Consequence:** `make test` is green on an empty pipeline; real behavior lands module-by-module starting Phase 1.

---

## 2026-09-03 — Registrant CIK vs. filing-agent CIK in SEC accession numbers

**Context:** While debugging against real SEC data, `financial_facts` was found to be silently wrong for a large minority of companies: a fact's `cik` was being parsed from the leading digits of its accession number (`adsh`, e.g. `0000320193-24-000123` -> `320193`), on the assumption those digits identify the registrant. They don't — they identify whoever *submitted* the accession, which for many filers is a third-party filing agent, not the company itself. This affected 24,397 facts across 143 of 500 S&P 500 companies (28.6%) before the fix.

**Options:**
- Keep deriving `cik` from the accession-number prefix — wrong for any company that uses a filing agent, i.e. most of the affected 143.
- Join to `stg_sub` (parsed from `sub.txt`, which has an explicit `cik` field SEC populates with the true registrant) and use that CIK instead.

**Decision:** `financial_facts.cik` is sourced from `stg_sub.cik` (the registrant), not from the accession-prefix-derived CIK. The staging table `stg_num` still records the accession-prefix CIK for traceability, but it's named `agent_cik` (not `cik`) to make its actual meaning unmistakable to anyone debugging via the staging layer directly.

**Consequence:** Every downstream table/view is now keyed on the real registrant CIK. Anyone writing staging-layer SQL must join `stg_num` to `stg_sub` on `adsh` to get the registrant CIK — `stg_num.agent_cik` alone is not reliable for that purpose. This also surfaced a related bug: the pinned S&P 500 CSV had ExxonMobil (XOM) mapped to CIK `2115436` instead of its real CIK `34088`, which meant XOM had zero rows anywhere downstream regardless of the agent/registrant fix — corrected separately in `data/sp500_constituents.csv`.

---

## 2026-09-03 — Dual-class shares share one SEC CIK

**Context:** A handful of S&P 500 constituents list multiple share classes as separate tickers (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) but file with the SEC as a single registrant — one CIK, one set of financial statements, two (or three) tickers. `companies`, `filings`, and `financial_facts` are all CIK-grained, so naively loading the constituent CSV as-is would try to insert two `companies` rows with the same CIK and violate the primary key.

**Options:**
- Make `companies` ticker-grained instead of CIK-grained (one row per ticker, duplicating CIK/financials across share classes) — would require duplicating every downstream fact per ticker for no real informational gain, and complicates the "one row per filer" mental model everywhere else in the schema.
- Dedup at load time, keeping one canonical ticker per CIK.

**Decision:** Dedup by CIK when building `companies`, keeping the first-listed ticker per CIK from `data/sp500_constituents.csv` (Class A share in all current cases, e.g. GOOGL over GOOG). The subordinate ticker simply doesn't appear in `companies` and any query against it returns no rows.

**Consequence:** Querying by a subordinate-class ticker (e.g. `GOOG`) finds nothing — a real gap, but a predictable and documented one (see `docs/schema.md`), not silent wrong data. If Phase 2+ needs both tickers addressable, `companies` would need a ticker-to-CIK mapping layer that keeps CIK-grained facts intact underneath.

---

## 2026-09-03 — Blank `value` in num.txt is valid data, not a malformed row

**Context:** The num.txt ingest loop counted any row where `float(row["value"])` raised `ValueError` as a "malformed row" and warned about it. In practice, every one of those rows (1,087 for 2024q3 alone) had a blank `value` field — which SEC legitimately publishes, not a parsing failure — while zero were actually malformed (bad `adsh`, non-numeric `qtrs`, garbage text). The blanket warning was permanent, 100%-false-positive noise that would mask a real parsing problem if one ever occurred, and the blank-value facts were being silently dropped from staging, contradicting the staging layer's purpose of mirroring exactly what SEC published.

**Options:**
- Keep dropping blank-value rows entirely — simplest, but loses real SEC data from staging and keeps the noisy/wrong warning.
- Store blank values as SQL `NULL` (DuckDB's `DOUBLE` column already allows this) and track them under a separate counter, reserving "skipped" for genuinely unparseable rows.

**Decision:** Blank `value` fields are stored as `NULL` and counted via a new `null_value_rows` stat, separate from `skipped_rows`. The "malformed rows skipped" warning now only fires for actual parse failures (bad `adsh` prefix, non-numeric `qtrs`, or a non-blank `value` that still fails `float()`).

**Consequence:** Staging now faithfully mirrors SEC's published data, including its blanks. `financial_facts` can contain `NULL` values for facts SEC reported without a number (e.g. certain footnoted disclosures) — a "value is NULL" isn't a fact that's missing entirely (the row exists, tagged, dated), it's a fact SEC published without a numeric value; callers should treat these accordingly rather than assuming every row has a usable number.

---

## 2026-09-03 — Concept-view dedup partition key vs. a bad SEC `fy` value

**Context:** `_build_concept_view`'s `QUALIFY ROW_NUMBER()` originally partitioned by `(cik, fiscal_year)` with no tiebreaker, so a same-priority tag tie inside one partition picked a nondeterministic row. Adding an `ORDER BY` tiebreaker (tag priority, then most-recent period end date, then most-recently filed) fixes ordinary nondeterminism, but Federal Realty (FRT, CIK 34903) exposed a deeper case: its two real, distinct 10-Ks (periods 2024-12-31 and 2025-12-31) both carry `sub.fy = '2024'` in SEC's own raw data — confirmed directly against `stg_sub`, not an artifact of our parsing. Because the partition key itself collides for two genuinely different filings, an `ORDER BY` tiebreaker alone can only pick one of the two deterministically — the other's figures still vanish from the view entirely, just consistently now instead of at random.

**Options:**
- Ship the `ORDER BY` tiebreaker only, accept that FRT's older-period figures are permanently dropped from concept views (deterministic, but still lossy).
- Re-derive `fiscal_year` for 10-Ks from `EXTRACT(YEAR FROM period_end_date)` instead of trusting SEC's `fy` field — rejected: breaks non-calendar fiscal-year companies (e.g. a January fiscal-year-end retailer's "FY2024" ends in calendar 2025; switching to period-year would relabel it FY2025, a correctness regression for the common case to fix one company's data-quality bug).
- Add `f.ddate` (the real period end date) to the `QUALIFY` `PARTITION BY`, alongside `fiscal_year`. Verified against the full built dataset first: FRT is the *only* `(cik, fiscal_year)` pair spanning more than one distinct `ddate` in all 500 companies, so this is a no-op everywhere else.

**Decision:** Partition by `(f.cik, fl.fiscal_year, f.ddate)`, keep the `fiscal_year`/`fiscal_period` labels as SEC reported them (no attempt to correct SEC's `fy` value). Both of FRT's real filings now appear as separate rows in every concept view instead of one silently winning a coin flip.

**Consequence:** No more data loss for FRT (or any future company hitting the same SEC data-quality pattern) — both real periods are visible, and `period_end_date` correctly distinguishes them. The known residual gap: both FRT rows still display `fiscal_year = 2024` in the `fiscal_year` column (SEC's own mislabeling is not corrected), so a caller filtering strictly by `fiscal_year = 2025` will still miss FRT's most recent filing — they'd need to use `period_end_date` instead for this specific company. This is called out here rather than silently fixed further, since correcting `fiscal_year` itself would require fiscal-year-end-aware logic per company, out of scope for this fix.
