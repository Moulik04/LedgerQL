# Evals

`gold.jsonl` holds >=150 hand-written question -> gold SQL pairs over the
EDGAR analyst schema (Phase 1+), spread across difficulty tiers: simple
lookup, aggregation, multi-join, time comparison, ambiguous/should-abstain,
adversarial/out-of-scope.

Run the full suite with `make eval`; it writes `reports/eval_<date>.md`
with a comparison table across configurations (model x N samples x
guardrails on/off).

Per the checkpoint rule in the master prompt: **don't add a gold case
you're not certain is correct** — stop and ask MJ instead.
