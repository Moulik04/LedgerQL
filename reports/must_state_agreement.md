# answer_must_state: MJ's blind labels against the grader and the first labeller

14 labelled (0 left blank), of the 28 items the first labeller labelled. **MJ vs the grader:** 6 of 14 (43%) gradable. **MJ vs the first labeller:** 8 of 14 (57%). These are the labels as MJ first gave them, blind; what re-reading changed is under *After adjudication*.

## What the check covers

| part | labelled by MJ | MJ = first labeller | MJ = grader |
|---|---|---|---|
| items the first labeller marked a judgement call | 4 of 4 | 2 | 0 |
| the other items | 10 of 24 | 6 | 6 |

The 14 items MJ did not label carry the first labeller's label only. The judgement calls are over-represented on purpose, so the overall rate above is not an estimate for all 28: the second row is the sample that speaks for the other items.

## After adjudication

MJ re-read the disagreements and wrote a final call in the note of 8 rows. The blind labels are kept as first given and every figure above is computed from them. MJ's blind label differed from the grader on 8 gradable items: **5 were resolved in the grader's favour on re-reading** (the blind label was wrong and the grader right), and 3 stand against the grader. **Final call vs the grader:** 11 of 14 (79%) gradable. **Final call vs the first labeller:** 11 of 14 (79%).

The grader's false fails by the final calls (stated, and graded not stated). The patterns are left as they are and these are listed in `evals/KNOWN_GOLD_ISSUES.md`:

- qwen25_32b U08[0]: In 2025, META's value was 366,021,000,000.0 USD, and in 2024, it was 276,054,000,000.0 USD.
- qwen25_32b M02[0]: JPMorgan Chase, with the ticker JPM, had total assets of 4,424,900,000,000.0.
- qwen3_30b U08[0]: The data shows a total value of 366,021,000,000 USD.

Its false passes by the final calls (not stated, and graded stated):

- none

| run | case | item | blind label | final call | grader | first labeller | MJ's note |
|---|---|---|---|---|---|---|---|
| qwen3_30b | L04 | 1 | True | False | False | False | FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip. |
| qwen3_30b | C06 | 0 | True | False | False | False | FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip. |
| qwen3_30b | M02 | 1 | True | False | False | False | FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip. |
| qwen25_32b | U08 | 0 | True | True | False | False | FINAL (MJ, 2026-10-07): stated. 'Which is base USD, not thousands or millions' explains the correct unit; it is not a phrase the answer must contain (the gold author's intent). A full unscaled figure in USD states the unit. The pattern is left unchanged: a known false fail. |
| qwen25_32b | M02 | 0 | True | True | False | True | FINAL (MJ, 2026-10-07): stated. The answer names total assets as the figure it reports. The pattern is left unchanged: a known false fail. |
| qwen3_30b | U07 | 1 | True | False | False | False | FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip. |
| qwen3_30b | U08 | 0 | True | True | False | False | FINAL (MJ, 2026-10-07): stated. 'Which is base USD, not thousands or millions' explains the correct unit; it is not a phrase the answer must contain (the gold author's intent). A full unscaled figure in USD states the unit. The pattern is left unchanged: a known false fail. |
| qwen25_32b | M01 | 0 | True | False | False | True | FINAL (MJ, 2026-10-07): not stated. A bare '2024' and '2025' for Apple does not say fiscal or calendar year, which is the ambiguity this item checks. |

## Per item

| case | item | n | MJ = first labeller | MJ = grader |
|---|---|---|---|---|
| A10 | 0 | 2 | 2 | 2 |
| C06 | 0 | 1 | 0 | 0 |
| L04 | 0 | 1 | 1 | 1 |
| L04 | 1 | 1 | 0 | 0 |
| M01 | 0 | 1 | 1 | 0 |
| M02 | 0 | 1 | 1 | 0 |
| M02 | 1 | 1 | 0 | 0 |
| U01 | 0 | 1 | 1 | 1 |
| U02 | 0 | 1 | 1 | 1 |
| U07 | 0 | 1 | 1 | 1 |
| U07 | 1 | 1 | 0 | 0 |
| U08 | 0 | 2 | 0 | 0 |

## Every disagreement

### qwen3_30b L04[1]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: The data shows a value of 206,803,000,000.0, which represents the total revenue for the fiscal year 2023. This amount is expressed in US dollars.

MJ's note: FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip.

### qwen3_30b C06[0]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: The total net income shown is 10,885,000,000.0 dollars. This represents the company's total net income for the fiscal year 2023.

MJ's note: FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip.

### qwen3_30b M02[1]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: JPMorgan Chase (JPM) had a maximum value of 4,424,900,000,000.0.

MJ's note: FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip.

### qwen25_32b U08[0]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: In 2025, META's value was 366,021,000,000.0 USD, and in 2024, it was 276,054,000,000.0 USD.

MJ's note: FINAL (MJ, 2026-10-07): stated. 'Which is base USD, not thousands or millions' explains the correct unit; it is not a phrase the answer must contain (the gold author's intent). A full unscaled figure in USD states the unit. The pattern is left unchanged: a known false fail.

### qwen25_32b M02[0]: MJ True, first labeller True, grader False (pattern False, judge False, decided by pattern)

Answer: JPMorgan Chase, with the ticker JPM, had total assets of 4,424,900,000,000.0.

MJ's note: FINAL (MJ, 2026-10-07): stated. The answer names total assets as the figure it reports. The pattern is left unchanged: a known false fail.

### qwen3_30b U07[1]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: The company's revenue was 47,941.0 millions of dollars.

MJ's note: FINAL (MJ, 2026-10-07): not stated. The text does not contain the item; the blind label was a slip.

### qwen3_30b U08[0]: MJ True, first labeller False, grader False (pattern False, judge False, decided by pattern)

Answer: The data shows a total value of 366,021,000,000 USD.

MJ's note: FINAL (MJ, 2026-10-07): stated. 'Which is base USD, not thousands or millions' explains the correct unit; it is not a phrase the answer must contain (the gold author's intent). A full unscaled figure in USD states the unit. The pattern is left unchanged: a known false fail.

### qwen25_32b M01[0]: MJ True, first labeller True, grader False (pattern False, judge False, decided by pattern)

Answer: In 2024, AAPL's value was 391,035,000,000.0, and in 2025, it was 416,161,000,000.0.

MJ's note: FINAL (MJ, 2026-10-07): not stated. A bare '2024' and '2025' for Apple does not say fiscal or calendar year, which is the ambiguity this item checks.
