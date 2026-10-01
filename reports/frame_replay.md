# The answer framing, replayed on the Phase 5 runs

For each answered record on a rubric case, the framing is rebuilt from its question, its recorded winning SQL and the database (`ledgerql/frame.py`, deterministic) and the **frame text alone** is graded against the case's `answer_must_state` items. It isolates what the new component states; whether the full answer then verifies depends on the writer no longer inventing a period, which only a live run shows.

| run | case | state it would emit | frame states every item | frame |
|---|---|---|---|---|
| qwen3_30b | L03 | ANSWER_WITH_ASSUMPTION | yes | The most recent fiscal year on record, fiscal year 2025 (period ended June 30, 2025), was used. |
| qwen3_30b | L04 | ANSWER_WITH_ASSUMPTION | yes | The most recent fiscal year on record, fiscal year 2026 (period ended January 31, 2026), was used. |
| qwen3_30b | L09 | ANSWER_WITH_ASSUMPTION | yes | The most recent fiscal year on record, fiscal year 2025 (period ended December 31, 2025), was used. |
| qwen3_30b | A10 | ANSWER | **no** | (none) |
| qwen3_30b | T06 | ANSWER | **no** | (none) |
| qwen3_30b | U01 | ANSWER | yes | Figures are shown in billions; the raw values are stored unscaled. |
| qwen3_30b | U02 | ANSWER_WITH_ASSUMPTION | yes | 2024 was read as fiscal year 2024, which ended on September 30, 2024. |
| qwen3_30b | U03 | ANSWER_WITH_ASSUMPTION | **no** | Total assets is a point-in-time balance, so the figures for different years are not added together; each year is shown separately. |
| qwen3_30b | U07 | ANSWER_WITH_ASSUMPTION | yes | The most recent fiscal year on record, fiscal year 2025 (period ended December 31, 2025), was used. Figures are shown in millions; the raw v |
| qwen3_30b | U08 | ANSWER_WITH_ASSUMPTION | yes | No fiscal year was specified, so the most recent one on record, fiscal year 2025 (period ended December 31, 2025), was used. The raw values  |
| qwen3_30b | M01 | ANSWER_WITH_ASSUMPTION | yes | No fiscal year was specified, so the most recent one on record, fiscal year 2025 (period ended September 30, 2025), was used. |
| qwen3_30b | M02 | ANSWER_WITH_ASSUMPTION | **no** | 'Biggest' was measured by total assets. All fiscal years on record were considered. |
| qwen3_30b | M06 | ANSWER_WITH_ASSUMPTION | yes | 'Profit' was interpreted as net income. |
| qwen3_30b | M08 | ANSWER_WITH_ASSUMPTION | yes | 'Google' was resolved to Alphabet Inc. (Class A) (ticker GOOGL). |
| qwen3_30b | C06 | ANSWER_WITH_ASSUMPTION | yes | It sums fiscal years 2024 and 2025, all the fiscal years on record for Tesla, Inc. |
| qwen25_32b | A10 | ANSWER | **no** | (none) |
| qwen25_32b | U01 | ANSWER | yes | Figures are shown in billions; the raw values are stored unscaled. |
| qwen25_32b | U02 | ANSWER_WITH_ASSUMPTION | yes | 2024 was read as fiscal year 2024, which ended on September 30, 2024. |
| qwen25_32b | U03 | ANSWER | **no** | (none) |
| qwen25_32b | U08 | ANSWER | yes | The raw values are stored in base USD, not thousands or millions. |
| qwen25_32b | M01 | ANSWER | **no** | (none) |
| qwen25_32b | M02 | ANSWER_WITH_ASSUMPTION | **no** | 'Biggest' was measured by total assets. All fiscal years on record were considered. |
| qwen25_32b | M06 | ANSWER_WITH_ASSUMPTION | yes | 'Profit' was interpreted as net income. |
| qwen25_32b | M07 | ANSWER | **no** | (none) |
| qwen25_32b | M08 | ANSWER_WITH_ASSUMPTION | yes | 'Google' was resolved to Alphabet Inc. (Class A) (ticker GOOGL). |
| qwen25_32b | H02 | ANSWER | **no** | (none) |
| qwen25_32b | C06 | ANSWER_WITH_ASSUMPTION | yes | It sums fiscal years 2024 and 2025, all the fiscal years on record for Tesla, Inc. |

## Summary (assumption cases only)

- qwen3_30b: the frame states every rubric item on 9 of 11 answered assumption cases
- qwen25_32b: the frame states every rubric item on 4 of 7 answered assumption cases
