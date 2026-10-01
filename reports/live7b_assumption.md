# Run summary (gold v3, strict)

States emitted: {'ANSWER_WITH_ASSUMPTION': 7, 'ABSTAIN': 9, 'ANSWER': 3}.

Assumption cases (19): answered correctly **6**, of which the assumption is **stated 4** (not stated 0, no rubric or not gradable 2); abstained 9 (reason stated 2); answered wrong 4.

Under the relaxed comparator (extra columns ignored): answered correctly 8, of which stated 6.

| case | expected | state | reason | correct (v3) | prose states items | text |
|---|---|---|---|---|---|---|
| L03 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | False | True | The value for Microsoft (MSFT) in fiscal year 2025 is $101,832,000,000.0. The most recent fiscal year on record, fiscal year 2025 (period ended June 3 |
| L04 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | True | True | The data in the table represents a value of 206,803,000,000.0. The most recent fiscal year on record, fiscal year 2026 (period ended January 31, 2026) |
| L09 | ANSWER_WITH_ASSUMPTION | ABSTAIN | LOW_AGREEMENT | False | None | The system could not settle on a single answer to this question with enough confidence, so it did not give one. |
| J02 | ANSWER_WITH_ASSUMPTION | ANSWER |  | True | None | The data in the table represents a value of 343,479,000,000.0. |
| J06 | ANSWER_WITH_ASSUMPTION | ABSTAIN | EXEC_ERROR | False | None | The query for this question could not be run against the database. |
| R07 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | False | True | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| U02 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | True | True | The data in the table represents a value of 391,035,000,000.0. 2024 was read as fiscal year 2024, which ended on September 30, 2024. |
| U03 | ANSWER_WITH_ASSUMPTION | ANSWER |  | False | False | The total assets of the entity are $724,221,000,000.0. |
| U05 | ANSWER_WITH_ASSUMPTION | ABSTAIN | EXEC_ERROR | False | None | The query for this question could not be run against the database. |
| U07 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | False | True | In 2025, The Coca-Cola Company (ticker KO) reported revenue of $47,941 million. The most recent fiscal year on record, fiscal year 2025 (period ended  |
| U08 | ANSWER_WITH_ASSUMPTION | ANSWER |  | False | True | The table shows the stock value of META for the fiscal years 2024 and 2025, with values in USD. The raw values are stored in base USD, not thousands o |
| M01 | ANSWER_WITH_ASSUMPTION | ABSTAIN | OUT_OF_SCOPE | False | None | This question is outside what this database can answer: it holds figures reported in the 10-K filings of S&P 500 companies. |
| M02 | ANSWER_WITH_ASSUMPTION | ABSTAIN | LOW_AGREEMENT | False | None | The system could not settle on a single answer to this question with enough confidence, so it did not give one. |
| M06 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | True | True | The data in the table represents a value of 59,248,000,000.0. 'Profit' was interpreted as net income. |
| M08 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | True | True | The data in the table represents a value of 350,018,000,000.0. 'Google' was resolved to Alphabet Inc. (Class A) (ticker GOOGL). |
| M09 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | False | None | No 10-K in this database covers Berkshire Hathaway for fiscal year 2024. |
| H06 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | True | True | JPMorgan Chase has no revenue figure under the standard revenue tags in this database. An absent tag means the figure was not reported under a known t |
| G04 | ANSWER_WITH_ASSUMPTION | ANSWER_WITH_ASSUMPTION |  | True | None | The data in the table represents a value of 208,160,000,000.0. The most recent fiscal year on record, fiscal year 2025 (period ended December 31, 2025 |
| G05 | ANSWER_WITH_ASSUMPTION | ABSTAIN | NO_DATA | False | None | No 10-K in this database has the requested figure for Amazon and Walmart. |
