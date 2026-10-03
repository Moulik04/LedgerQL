# Task 2/3 acceptance from the pipeline runs (gold v3, strict)

## Qwen3-30B pipeline (47314853)

Integrity: 103 records, **PARTIAL: 27 of 103 records failed for infrastructure reasons and are excluded: ['O07', 'O08', 'S07', 'S08', 'S09', 'S10', 'S11', 'H01', 'H02', 'H03', 'H04', 'H05', 'H06', 'H07', 'H08', 'G01', 'G02', 'G03', 'G04', 'G05', 'G06', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06']**. Figures cover 76 records.

States emitted: {'ANSWER': 32, 'ANSWER_WITH_ASSUMPTION': 10, 'ABSTAIN': 34}.

| expected \ observed | ANSWER | ANSWER_WITH_ASSUMPTION | ABSTAIN |
|---|---|---|---|
| ANSWER | 29 | 0 | 10 |
| ANSWER_WITH_ASSUMPTION | 2 | 10 | 4 |
| ABSTAIN | 1 | 0 | 20 |

Execution accuracy on the `ANSWER` cases that ran: 22/39 (strict v3), 29/39 relaxed.
Hallucinated-number rate including years, verified as the pipeline verified it: **0.0%** (0 of 42 answered; []).
Confidently wrong: 12 of 42 answered. Coverage: 41 of 55 answerable.

**Assumption cases (16 that ran): answered correctly with the assumption stated: 8** (baseline 0 of 19). Answered correctly 9, of which not stated 0, no rubric items 1; abstained 4 (reason stated 1); answered wrong 3.
Ablation (framing text removed, same records): stated 0.

Task 2's six named cases (score 1.0 = correct value and the assumption stated): M01 0 (wrong value), M02 0 (wrong value), M06 1.0, M08 1.0, U02 1.0, U07 1.0.

Rubric pass rate by tier (records on rubric cases that state every item; not gradable counts as not stated), baseline run vs this run, same cases:

| tier | baseline | this run |
|---|---|---|
| unit_period | 1/6 | 5/6 |
| ambiguous | 0/5 | 3/5 |
| schema_bait | 0/0 | 0/0 |

## Qwen2.5-32B AWQ pipeline (47314855)

Integrity: 103 records, complete. Figures cover 103 records.

States emitted: {'ANSWER': 38, 'ABSTAIN': 59, 'ANSWER_WITH_ASSUMPTION': 6}.

| expected \ observed | ANSWER | ANSWER_WITH_ASSUMPTION | ABSTAIN |
|---|---|---|---|
| ANSWER | 32 | 2 | 16 |
| ANSWER_WITH_ASSUMPTION | 3 | 4 | 12 |
| ABSTAIN | 3 | 0 | 31 |

Execution accuracy on the `ANSWER` cases that ran: 29/50 (strict v3), 37/50 relaxed.
Hallucinated-number rate including years, verified as the pipeline verified it: **0.0%** (0 of 44 answered; []).
Confidently wrong: 15 of 44 answered. Coverage: 41 of 69 answerable.

**Assumption cases (19 that ran): answered correctly with the assumption stated: 1** (baseline 0 of 19). Answered correctly 1, of which not stated 0, no rubric items 0; abstained 12 (reason stated 2); answered wrong 6.
Ablation (framing text removed, same records): stated 0.

Task 2's six named cases (score 1.0 = correct value and the assumption stated): M01 0 (wrong value), M02 0 (wrong value), M06 0 (right value, extra columns: strict fails, relaxed passes), M08 0 (right value, extra columns: strict fails, relaxed passes), U02 1.0, U07 0 (abstained).

Rubric pass rate by tier (records on rubric cases that state every item; not gradable counts as not stated), baseline run vs this run, same cases:

| tier | baseline | this run |
|---|---|---|
| unit_period | 1/6 | 4/6 |
| ambiguous | 1/5 | 2/5 |
| schema_bait | 0/3 | 3/3 |
