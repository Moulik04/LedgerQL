# LedgerQL Eval

Date: 2026-09-14
Model: Qwen/Qwen3-Coder-30B-A3B-Instruct
Candidate temperature: 0.7
Answer temperature: 0.2
Seed: 42
Candidates per question (N): 5
Low-agreement threshold: 0.6

## Execution accuracy

Overall (on 'ANSWER'-expected cases): 62.0%

| Tier | Accuracy |
|---|---|
| adversarial | 100.0% |
| aggregation | 81.8% |
| ambiguous | no positive control in this tier |
| calibration_twin | 100.0% |
| grounding | 33.3% |
| lookup | 66.7% |
| out_of_scope | no positive control in this tier |
| ratio | 16.7% |
| raw_facts | 20.0% |
| schema_bait | no positive control in this tier |
| time | 57.1% |
| unit_period | 100.0% |

## Hallucinated-number rate

0.0% of 72 answered cases stated a number not present in that query's own executed result.

This checks the answer against its own query's result set, not against the gold SQL -- it catches the model inventing or mistranscribing a number, not the model answering a different question than the one asked. A wrong-but-self-consistent SQL query (e.g. an exact-match filter where gold uses a fuzzy one, or a different date column) can still score 0% hallucinated: every number it states really is in its own result, that result is just an answer to the wrong query. That failure mode shows up in execution accuracy, not here.

## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)

53 cases where a guardrail-aware system should abstain or state an assumption. This section is descriptive (raw attempted/errored counts, not a pass/fail score) -- the Confidence & abstain section below is where abstain behavior is actually scored (precision/recall):

- Attempted an answer anyway: 31
- Errored during execution (e.g. adversarial DML hitting the read-only connection): 15

### Per-tier breakdown of non-ANSWER outcomes

| Tier | Attempted anyway | Errored |
|---|---|---|
| adversarial | 1 | 7 |
| ambiguous | 7 | 0 |
| grounding | 2 | 1 |
| lookup | 3 | 0 |
| out_of_scope | 3 | 1 |
| ratio | 1 | 0 |
| raw_facts | 2 | 0 |
| schema_bait | 4 | 4 |
| time | 2 | 1 |
| unit_period | 6 | 1 |

## Guardrail catch rate

Adversarial-tier target: 100% (Phase 3 acceptance criterion).

| Tier | Catch rate |
|---|---|
| adversarial | 55.6% |
| out_of_scope | 37.5% |
| schema_bait | 14.3% |

## Confidence & abstain

Abstain precision: 29.0% (9/31 abstains were correct) -- Phase 4 acceptance target: >= 80%.
Abstain recall: 17.0% (9/53 cases that should have abstained were caught).

## Ablation

| Configuration | Execution accuracy | Hallucinated-number rate | Adversarial guardrail catch |
|---|---|---|---|
| naive (Phase 2) | 58.0% | 32.5% | n/a |
| +static guardrails (Phase 3) | 58.0% | 28.6% | 88.9% |
| +self-consistency & verifier (Phase 4) | 62.0% | 0.0% | 55.6% |

Full per-case results: `eval_2026-09-14.jsonl`
