# Phase 3 Baseline

Date: 2026-09-10
Model: qwen2.5-coder:7b
Temperature: 0.2
Seed: 42

## Execution accuracy

Overall (on 'ANSWER'-expected cases): 58.0%

| Tier | Accuracy |
|---|---|
| adversarial | 100.0% |
| aggregation | 81.8% |
| ambiguous | no positive control in this tier |
| calibration_twin | 83.3% |
| grounding | 66.7% |
| lookup | 77.8% |
| out_of_scope | no positive control in this tier |
| ratio | 33.3% |
| raw_facts | 0.0% |
| schema_bait | no positive control in this tier |
| time | 14.3% |
| unit_period | 100.0% |

## Hallucinated-number rate

28.6% of 70 answered cases stated a number not present in that query's own executed result.

## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)

53 cases where a guardrail-aware system should abstain or state an assumption. Phase 2 has no abstain logic, so this section is descriptive, not scored:

- Attempted an answer anyway: 30
- Errored during execution (e.g. adversarial DML hitting the read-only connection): 16

### Per-tier breakdown of non-ANSWER outcomes

| Tier | Attempted anyway | Errored |
|---|---|---|
| adversarial | 1 | 7 |
| ambiguous | 7 | 0 |
| grounding | 3 | 0 |
| lookup | 3 | 0 |
| out_of_scope | 4 | 0 |
| ratio | 1 | 0 |
| raw_facts | 1 | 1 |
| schema_bait | 3 | 5 |
| time | 2 | 1 |
| unit_period | 5 | 2 |

## Guardrail catch rate

Adversarial-tier target: 100% (Phase 3 acceptance criterion).

| Tier | Catch rate |
|---|---|
| adversarial | 88.9% |
| out_of_scope | 50.0% |
| schema_bait | 28.6% |

Full per-case results: `baseline_2026-09-10.jsonl`
