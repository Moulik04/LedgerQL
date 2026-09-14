# Phase 5: Remote Model Comparison

Real 103-case eval (`evals/gold.jsonl`) run against three models, same
guardrails/self-consistency/verifier pipeline, same seed. The 7B run is
local (M2, Metal, via Ollama); the 32B and 30B runs are on PSC Bridges-2
(H100-80 GPUs, via vLLM per `LEDGERQL_MASTER_PROMPT.md`'s explicit
preference) — see `docs/bridges2.md` for the real, verified cluster setup
and the full investigation behind these numbers.

| Model | Precision / GPUs | Execution accuracy | Hallucinated-number rate | Abstain precision | Adversarial guardrail catch |
|---|---|---|---|---|---|
| qwen2.5-coder:7b (local baseline) | Ollama default quant, M2 Metal | 54.0% | 0.0% | 27.1% | 88.9% |
| Qwen2.5-Coder-32B-Instruct-AWQ (Bridges-2) | AWQ 4-bit, 1x H100-80 | 52.0% | 0.0% | 27.5% | 55.6% |
| Qwen3-Coder-30B-A3B-Instruct (Bridges-2) | fp16, 1x H100-80 | **62.0%** | 0.0% | 29.0% | 55.6% |

## Findings

**Scale alone doesn't help — generation and precision do.** The same-family
32B AWQ model (a straight scale-up of the 7B baseline, isolating "does more
parameters help" as close to a single variable as this comparison could
get) showed essentially *no* improvement — execution accuracy actually
dropped two points, abstain precision moved by half a point. Whether that's
the 4-bit quantization eating into quality, or simply that this pipeline's
prompts were empirically tuned against the 7B's specific behavior and don't
transfer cleanly to a larger sibling, isn't separable from this comparison
alone — but the headline result is clear: bigger, by itself, was not
better here.

**Qwen3-Coder-30B-A3B-Instruct at full fp16 is a real, meaningful jump**:
+8 points over the 7B baseline, +10 over the 32B AWQ model, while holding
hallucinated-number rate at 0%. This confounds two variables at once
(newer model generation *and* no quantization, vs. the 32B run's older
generation *and* 4-bit quantization) — this comparison can't cleanly credit
one or the other, only that the combination helped.

**Hallucinated-number rate held at 0.0% across all three models.** This is
the strongest signal in the whole comparison: Phase 4's self-consistency +
numeric verifier pipeline is robustly preventing hallucinated numbers
regardless of which model generates the underlying SQL/answer. The safety
property this phase exists to protect is not model-dependent.

**Abstain precision stayed flat and far below target (27.1% / 27.5% /
29.0%, target ≥80%) even under the model that meaningfully improved
execution accuracy.** This is informative on its own: if abstain precision
were primarily "the model isn't capable enough," a real 8-10-point
execution-accuracy jump should have moved it more than 2 points. It didn't.
This supports the root-cause breakdown already on record in `DECISIONS.md`
(2026-09-11, Phase 4) — that the shortfall is mostly structural
(gold-vocabulary mismatch under Core-only scope) and genuine hard-query
self-consistency disagreement, not primarily a raw-capability gap a bigger
model closes.

**The adversarial guardrail catch-rate drop (88.9% → 55.6%, identically for
both bigger models) is not a safety regression.** Investigated directly per
model rather than assumed identical because the percentages matched: in
both cases, every "miss" is either (a) a case that still correctly
abstained, just via `LOW_AGREEMENT`/`COST_LIMIT`/`EXEC_ERROR` instead of the
gold set's expected `OUT_OF_SCOPE` reason code, or (b) a case where the
model's own SQL generation silently neutralized the injected malicious
instruction (dropped a `DROP TABLE` clause, wrapped a requested `UPDATE` as
an inert string literal, turned "print the .env file" into an empty
`SELECT ... LIMIT 0`) and either abstained or answered the legitimate part
of the question truthfully. Both bigger models did this on *more* cases
than the 7B did — if anything a sign of growing robustness to injection,
not declining safety. `guardrails.py`'s catch-rate metric specifically
counts whether its own blocking mechanism fired, and doesn't credit "the
attack never produced anything to catch." No destructive SQL executed and
no false information was stated in any of the investigated cases, across
any model.

## Recommendation

Something in between the two poles, stated precisely: **scale alone is not
worth pursuing further** (the 32B AWQ result closes that door for this
model family), but **Qwen3-Coder-30B-A3B-Instruct's real improvement is
worth taking seriously** rather than dismissing as noise — a genuine
8-10-point execution-accuracy gain with zero hallucination-rate cost is
significant. At the same time, **abstain precision remains the real open
problem, and this comparison's evidence points away from "a smarter model
fixes it"** — even the improved model barely moved that number, which
argues for prioritizing the structural fixes already identified in Phase
4's `DECISIONS.md` (or the deferred calibration-framework work) over
further model-scale chasing.

This does **not** by itself justify standing up a permanent remote-inference
path for production use — that's a real operational cost (an H100
allocation is a shared, finite academic resource, not a standing service)
against a meaningful-but-not-transformative accuracy gain, and abstain
precision (arguably the more safety-relevant number) barely moved. Whether
that tradeoff is worth making is a product decision for the project owner,
not something this comparison settles on its own.
