# LedgerQL Eval

Date: 2026-09-11
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

0.0% of 55 answered cases stated a number not present in that query's own executed result.

This checks the answer against its own query's result set, not against the gold SQL -- it catches the model inventing or mistranscribing a number, not the model answering a different question than the one asked. A wrong-but-self-consistent SQL query (e.g. an exact-match filter where gold uses a fuzzy one, or a different date column) can still score 0% hallucinated: every number it states really is in its own result, that result is just an answer to the wrong query. That failure mode shows up in execution accuracy, not here.

## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)

53 cases where a guardrail-aware system should abstain or state an assumption. This section is descriptive (raw attempted/errored counts, not a pass/fail score) -- the Confidence & abstain section below is where abstain behavior is actually scored (precision/recall):

- Attempted an answer anyway: 22
- Errored during execution (e.g. adversarial DML hitting the read-only connection): 10

### Per-tier breakdown of non-ANSWER outcomes

| Tier | Attempted anyway | Errored |
|---|---|---|
| adversarial | 1 | 7 |
| ambiguous | 6 | 0 |
| grounding | 3 | 0 |
| lookup | 2 | 0 |
| out_of_scope | 1 | 0 |
| ratio | 1 | 0 |
| raw_facts | 1 | 1 |
| schema_bait | 1 | 1 |
| time | 1 | 0 |
| unit_period | 5 | 1 |

## Guardrail catch rate

Adversarial-tier target: 100% (Phase 3 acceptance criterion).

| Tier | Catch rate |
|---|---|
| adversarial | 88.9% |
| out_of_scope | 50.0% |
| schema_bait | 14.3% |

## Confidence & abstain

Abstain precision: 27.1% (13/48 abstains were correct) -- Phase 4 acceptance target: >= 80%.
Abstain recall: 24.5% (13/53 cases that should have abstained were caught).

## Ablation

| Configuration | Execution accuracy | Hallucinated-number rate | Adversarial guardrail catch |
|---|---|---|---|
| naive (Phase 2) | 58.0% | 32.5% | n/a |
| +static guardrails (Phase 3) | 58.0% | 28.6% | 88.9% |
| +self-consistency & verifier (Phase 4) | 54.0% | 0.0% | 88.9% |

Full per-case results: `eval_2026-09-11.jsonl`
