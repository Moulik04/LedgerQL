# Task 2/3 acceptance from the pipeline runs (gold v3, strict)

## Qwen3-30B pipeline (47367323)

Integrity: 103 records, complete. Figures cover 103 records.

States emitted: {'ANSWER': 42, 'ANSWER_WITH_ASSUMPTION': 13, 'ABSTAIN': 48}.

| expected \ observed | ANSWER | ANSWER_WITH_ASSUMPTION | ABSTAIN |
|---|---|---|---|
| ANSWER | 38 | 1 | 11 |
| ANSWER_WITH_ASSUMPTION | 1 | 12 | 6 |
| ABSTAIN | 3 | 0 | 31 |

Execution accuracy on the `ANSWER` cases that ran: 31/50 (strict v3), 40/50 relaxed.
Hallucinated-number rate including years, verified as the pipeline verified it: **0.0%** (0 of 55 answered; []).
Confidently wrong: 14 of 55 answered. Coverage: 52 of 69 answerable.

**Assumption cases (19 that ran): answered correctly with the assumption stated: 9** (baseline 0 of 19). Answered correctly 11, of which not stated 0, no rubric items 2; abstained 6 (reason stated 2); answered wrong 2.
Ablation (framing text removed, same records): stated 0.

Task 2's six named cases (score 1.0 = correct value and the assumption stated): M01 1.0, M02 0 (wrong value), M06 1.0, M08 1.0, U02 1.0, U07 1.0.

Rubric pass rate by tier (records on rubric cases that state every item; not gradable counts as not stated), baseline run vs this run, same cases:

| tier | baseline | this run |
|---|---|---|
| unit_period | 1/6 | 5/6 |
| ambiguous | 0/5 | 4/5 |
| schema_bait | 0/3 | 3/3 |
