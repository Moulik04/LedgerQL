# Refusal rubric items, replayed deterministically

Each abstain's explanation is rebuilt from its reason code, the question and the database (`ledgerql/refusal.py`: templates and a documented-gaps registry, no model) and graded against the case's rubric items (`evals/must_state.py`). Not a model run: the text is a pure function of the recorded abstain.

| run | case | reason | refusal states the item(s) | refusal text |
|---|---|---|---|---|
| qwen3_30b | R07 | NO_DATA | yes | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| qwen3_30b | U06 | NO_DATA | yes | No 8-K filings are loaded for Tesla, Inc.: the forms present for it are 10-K and 10-Q. |
| qwen3_30b | M07 | NO_DATA | yes | Only the canonical ticker GOOGL is loaded for this company; GOOG is another share class and is not a separate row. |
| qwen3_30b | S11 | SCHEMA_MISMATCH | yes | The staging tables (stg_sub, stg_num, stg_tag) exist only for debugging and are never exposed to query generation, so they cannot be queried. |
| qwen3_30b | H02 | NO_DATA | yes | Employee counts are not in this database: it draws only on the primary financial statements of 10-K filings, which do not include headcount. |
| qwen3_30b | H04 | NO_DATA | yes | This database holds consolidated, non-dimensional values only, so segment and geographic breakdowns are not available: they are excluded by design. |
| qwen3_30b | H06 | NO_DATA | yes | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| qwen25_32b | T06 | NO_DATA | yes | This database holds annual figures only (10-K filings, fiscal-year periods); quarterly figures are not loaded. |
| qwen25_32b | R07 | NO_DATA | yes | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| qwen25_32b | U06 | NO_DATA | yes | No 8-K filings are loaded for Tesla, Inc.: the forms present for it are 10-K and 10-Q. |
| qwen25_32b | S11 | SCHEMA_MISMATCH | yes | The staging tables (stg_sub, stg_num, stg_tag) exist only for debugging and are never exposed to query generation, so they cannot be queried. |
| qwen25_32b | H04 | EXEC_ERROR | yes | This database holds consolidated, non-dimensional values only, so segment and geographic breakdowns are not available: they are excluded by design. |
| qwen25_32b | H06 | NO_DATA | yes | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |

Rubric cases that abstained in no run listed above were answered by the model instead.
