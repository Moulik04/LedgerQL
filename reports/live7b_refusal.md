# Run summary (gold v3, strict)

States emitted: {'ABSTAIN': 8}.

Assumption cases (2): answered correctly **0**, of which the assumption is **stated 0** (not stated 0, no rubric or not gradable 0); abstained 2 (reason stated 2); answered wrong 0.

Under the relaxed comparator (extra columns ignored): answered correctly 0, of which stated 0.

| case | expected | state | reason | correct (v3) | prose states items | text |
|---|---|---|---|---|---|---|
| T06 | ABSTAIN | ABSTAIN | NO_DATA | None | None | This database holds annual figures only (10-K filings, fiscal-year periods); quarterly figures are not loaded. |
| R07 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | False | True | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| U06 | ABSTAIN | ABSTAIN | NO_DATA | None | None | No 8-K filings are loaded for Tesla, Inc.: the forms present for it are 10-K and 10-Q. |
| M07 | ABSTAIN | ABSTAIN | NO_DATA | None | None | Only the canonical ticker GOOGL is loaded for this company; GOOG is another share class and is not a separate row. |
| S11 | ABSTAIN | ABSTAIN | SCHEMA_MISMATCH | None | None | The staging tables (stg_sub, stg_num, stg_tag) exist only for debugging and are never exposed to query generation, so they cannot be queried. |
| H02 | ABSTAIN | ABSTAIN | NO_DATA | None | None | Employee counts are not in this database: it draws only on the primary financial statements of 10-K filings, which do not include headcount. |
| H04 | ABSTAIN | ABSTAIN | SCHEMA_MISMATCH | None | None | This database holds consolidated, non-dimensional values only, so segment and geographic breakdowns are not available: they are excluded by design. |
| H06 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | True | True | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
