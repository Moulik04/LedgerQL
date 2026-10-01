# answer_must_state: calibration against hand labels

28 hand labels on real answers; grader agrees on 26 of 28 gradable (false passes 0, false fails 2, not gradable 0).
The judge (logged apart, decides only `primary: judge` items) agrees with the labels on 20 of 28 votes (0 unparsed).

| run | case | item | label | pattern | judge | decides | graded | note |
|---|---|---|---|---|---|---|---|---|
| qwen3_30b | L03 | 0 | True | True | False | pattern | True | states 'fiscal year 2022' (wrong year; correctness is the year verifie |
| qwen3_30b | L04 | 0 | True | True | False | pattern | True | states 'fiscal year 2023' |
| qwen3_30b | L04 | 1 | False | False | False | pattern | False |  |
| qwen3_30b | L09 | 0 | True | True | False | pattern | True | states 'fiscal year 2023' |
| qwen3_30b | A10 | 0 | False | False | False | judge | False |  |
| qwen3_30b | U01 | 0 | True | True | False | pattern | True | 'billions of dollars' |
| qwen3_30b | U02 | 0 | False | False | False | pattern | False | states fiscal year 2022, not 2024, and no September date |
| qwen3_30b | U03 | 0 | False | False | False | judge | False | shows two values with 'no additional context' |
| qwen3_30b | U07 | 0 | True | True | True | pattern | True | 'millions of dollars' |
| qwen3_30b | U07 | 1 | False | False | False | pattern | False | no year stated |
| qwen3_30b | U08 | 0 | False | False | False | pattern | False | JUDGEMENT CALL: says 'USD' but not that it is base USD rather than tho |
| qwen3_30b | M01 | 0 | True | True | False | pattern | True | states 'fiscal year 2022' (presence) |
| qwen3_30b | M02 | 0 | False | False | False | pattern | False | 'maximum value', no metric named |
| qwen3_30b | M02 | 1 | False | False | False | pattern | False |  |
| qwen3_30b | M06 | 0 | False | False | False | pattern | False | no 'net income' |
| qwen3_30b | M08 | 0 | False | False | False | pattern | False | no Alphabet or GOOGL |
| qwen3_30b | C06 | 0 | False | False | False | pattern | False | mentions one year only |
| qwen25_32b | A10 | 0 | False | False | False | judge | False |  |
| qwen25_32b | U01 | 0 | True | True | True | pattern | True | '391.035 billion dollars' |
| qwen25_32b | U02 | 0 | False | False | False | pattern | False |  |
| qwen25_32b | U03 | 0 | False | False | False | judge | False | sums the two values, the opposite of the item |
| qwen25_32b | U08 | 0 | False | False | False | pattern | False | JUDGEMENT CALL: as for the 30B |
| qwen25_32b | M01 | 0 | True | False | False | pattern | False | JUDGEMENT CALL: gives both years ('In 2024 ... in 2025'); years stated |
| qwen25_32b | M02 | 0 | True | False | False | pattern | False | JUDGEMENT CALL: 'had total assets of ...' names the metric without say |
| qwen25_32b | M02 | 1 | False | False | False | pattern | False |  |
| qwen25_32b | M06 | 0 | False | False | False | pattern | False | no 'net income' |
| qwen25_32b | M08 | 0 | True | True | False | pattern | True | 'the value for ticker GOOGL' |
| qwen25_32b | C06 | 0 | False | False | False | pattern | False |  |
