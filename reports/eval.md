# LedgerQL Eval

Date: 2026-09-20
Model: qwen2.5-coder:7b
Candidate temperature: 0.7
Answer temperature: 0.2
Seed: 42
Candidates per question (N): 5
Low-agreement threshold: 0.6

## Execution accuracy

Overall (on 'ANSWER'-expected cases): 54.0%

| Tier | Accuracy |
|---|---|
| adversarial | 100.0% |
| aggregation | 81.8% |
| ambiguous | no positive control in this tier |
| calibration_twin | 83.3% |
| grounding | 33.3% |
| lookup | 66.7% |
| out_of_scope | no positive control in this tier |
| ratio | 33.3% |
| raw_facts | 0.0% |
| schema_bait | no positive control in this tier |
| time | 14.3% |
| unit_period | 100.0% |

## Hallucinated-number rate

0.0% of 44 answered cases stated a number not present in that query's own executed result.

This checks the answer against its own query's result set, not against the gold SQL -- it catches the model inventing or mistranscribing a number, not the model answering a different question than the one asked. A wrong-but-self-consistent SQL query (e.g. an exact-match filter where gold uses a fuzzy one, or a different date column) can still score 0% hallucinated: every number it states really is in its own result, that result is just an answer to the wrong query. That failure mode shows up in execution accuracy, not here.

## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)

53 cases where a guardrail-aware system should abstain or state an assumption. This section is descriptive (raw attempted/errored counts, not a pass/fail score) -- the Confidence & abstain section below is where abstain behavior is actually scored (precision/recall):

- Attempted an answer anyway: 12
- Errored during execution (e.g. adversarial DML hitting the read-only connection): 11

### Per-tier breakdown of non-ANSWER outcomes

| Tier | Attempted anyway | Errored |
|---|---|---|
| adversarial | 0 | 9 |
| ambiguous | 3 | 0 |
| grounding | 1 | 0 |
| lookup | 2 | 0 |
| out_of_scope | 1 | 0 |
| ratio | 0 | 0 |
| raw_facts | 1 | 0 |
| schema_bait | 0 | 1 |
| time | 0 | 0 |
| unit_period | 4 | 1 |

## Guardrail catch rate

Adversarial-tier target: 100% (Phase 3 acceptance criterion).

| Tier | Catch rate |
|---|---|
| adversarial | 100.0% |
| out_of_scope | 50.0% |
| schema_bait | 14.3% |

## Confidence & abstain

Two different questions, reported separately per PHASE_5_5_AMENDMENT_1.md (a single 'abstain precision' number silently conflated them before this): was abstaining the right *decision*, and separately, was the *reason code* also right.

Abstain precision (decision): 69.5% (41/59 abstains were the right call, any reason code).
Abstain precision (strict): 32.2% (19/59 abstains had the right call AND the right reason code) -- Phase 4 acceptance target: >= 80%.
Abstain recall (decision): 94.1% (32/34 cases that *must* be refused were caught, any reason code).
Abstain recall (strict): 55.9% (19/34 cases that *must* be refused were caught with the right reason code).

Recall's denominator is the 34 cases where refusing is *required*, not the 53-case union with ANSWER_WITH_ASSUMPTION. On those, refusing is only an accepted alternative -- answering correctly with the assumption stated is the ideal outcome -- so the union denominator scored the ideal outcome as a missed abstain and rewarded over-abstention. They are reported on their own line below. Precision still counts an abstain on either population as a correct decision.

Assumption-case handling: 57.9% (11/19 of the ANSWER_WITH_ASSUMPTION cases did one of the two acceptable things: abstained, or answered with a result matching gold). The stronger check -- that the assumption was also *stated* -- needs `answer_must_state` rubric grading, which is not implemented yet.
Reason-code accuracy: 46.3% (19/41 of the abstains that were the right call also named the right reason).
Always-abstain baseline: 33.0% -- the precision a system that refused every single question would get (an ANSWER_WITH_ASSUMPTION case can never score correct under that policy either, since a real abstain always sets a reason code and gold's own code for those is None). Every real run so far has landed at or below this.

## Ablation

| Configuration | Execution accuracy | Hallucinated-number rate | Adversarial guardrail catch |
|---|---|---|---|
| naive (Phase 2) | 58.0% | 32.5% | n/a |
| +static guardrails (Phase 3) | 58.0% | 28.6% | 88.9% |
| +self-consistency & verifier (Phase 4) | 54.0% | 0.0% | 100.0% |

## Repair

One repair attempt before abstaining (ledgerql/repair.py), split by what triggered it so each trigger's value is separable. *Rescued* = the repair turned an abstain into an answer. *Rescued correct* = the rescue matches gold on a case where answering is right. *Should have abstained* = the rescue answered a case that required a refusal -- the harm a repair pass risks, never netted against the wins.

| Trigger | Attempted | Rescued | Rescue rate | Rescued correct | Should have abstained |
|---|---|---|---|---|---|
| exec_error | 7 | 0 | 0.0% | 0 | 0 |
| schema_mismatch | 0 | 0 | 0.0% | 0 | 0 |
| empty_entity_bound | 15 | 0 | 0.0% | 0 | 0 |
| total | 22 | 0 | 0.0% | 0 | 0 |

Full per-case results: `eval_2026-09-20.jsonl`
