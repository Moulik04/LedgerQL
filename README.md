# LedgerQL

An auditable natural-language-to-SQL system for financial data — layered guardrails, hallucination detection, and a full audit trail on every query. Runs entirely on local, open-weight models. No hosted LLM APIs, no cloud bill.

> Ask a plain-English question about company financials. LedgerQL returns a correct SQL query, the executed result, and a grounded answer with a confidence score — **or it refuses**, with a reason. It never returns a fabricated number.

**Status:** Phase 4 complete; Phase 5's model-comparison sub-goal complete (log-mined gold-set expansion still pending). A real Bridges-2 comparison found a newer full-precision model (`Qwen3-Coder-30B-A3B-Instruct`) lifts execution accuracy to 62.0% (from the local `qwen2.5-coder:7b` baseline's 54.0%) at 0.0% hallucinated-number rate, while same-family scale alone did not help — see `DECISIONS.md` and `reports/phase5_model_comparison.md`. The live pipeline's default stays `qwen2.5-coder:7b` locally via Ollama; abstain precision remains the open problem at 27-29% across every model tested (target ≥80%).

## Why

Text-to-SQL demos are easy to make look good and easy to make wrong in ways that don't show up until someone trusts a number that was never actually in the data. LedgerQL treats that as the core problem: every generated query is statically validated before it can run, every answer is checked against the query result it claims to summarize, and low-confidence or out-of-scope questions get a clean refusal with a machine-readable reason code instead of a guess.

## Architecture

```
question
   │
   ▼
[1] Intent & scope classifier ── out of scope / unsafe → REFUSE (logged)
   │
   ▼
[2] Schema retrieval (relevant tables/columns, few-shot examples)
   │
   ▼
[3] SQL generation (local LLM, N samples)
   │
   ▼
[4] Static guardrails (AST-level: single SELECT only, schema-valid, cost cap)
   │
   ▼
[5] Execution — read-only DuckDB connection, timeout enforced
   │
   ▼
[6] Self-consistency vote across candidates
   │
   ▼
[7] Grounded answer generation + numeric verifier (unsupported number → ABSTAIN)
   │
   ▼
[8] Confidence score + audit record → API response
```

## Hallucination detection

| Layer | Catches |
|---|---|
| Schema validation | Invented tables/columns, wrong joins |
| Self-consistency | Unstable interpretations of ambiguous questions |
| Result-grounded answer + numeric verifier | Numbers in the answer not present in the data |
| Unit/period check | Answer in wrong unit (thousands vs. units) or wrong fiscal period |
| Abstain policy | Everything above with confidence below threshold |

Every abstain returns a reason code (`OUT_OF_SCOPE`, `SCHEMA_MISMATCH`, `LOW_AGREEMENT`, `UNGROUNDED_ANSWER`, `EXEC_ERROR`, `COST_LIMIT`) and a human-readable explanation.

## Stack

- **Data:** SEC EDGAR Financial Statement Data Sets, loaded into DuckDB
- **Generation:** local models via Ollama (`qwen2.5-coder:7b` default)
- **Guardrails:** `sqlglot` AST validation, schema enforcement, read-only execution
- **Surface:** FastAPI (`/ask`, `/audit/{id}`, `/health`) + a Streamlit demo UI
- **Eval:** hand-written gold set (`evals/gold.jsonl`) scored on execution accuracy, guardrail catch rate, abstain precision, and hallucinated-number rate — with ablations

## Getting started

```bash
brew install uv          # if you don't already have it
make setup                # installs deps, sets up pre-commit
make test                  # runs the test suite
```

## Evaluation

The eval suite is the point of the project, not an afterthought. `make eval` runs the gold set across configurations (model × sample count × guardrails on/off) and writes a comparison report to `reports/`. The "guardrails off" column is the baseline the rest of the project is measured against.

### A metric that was measuring two things at once

The headline abstain-precision number sat at 27–29% across three models — *below* the 33.0% a system that simply refused every single question would score. That looked like an abstain layer carrying no signal at all.

It wasn't. `evals/README.md` defined abstain precision as a question about the **decision** (was refusing the right call), but the harness implemented it as decision **and** exact reason-code match, silently folding in a second metric the same doc listed separately. Split apart on the same run: **71.0% decision precision, 40.9% reason-code accuracy** — a system that refuses correctly most of the time and then explains itself correctly less than half the time. Two different failures, two different fixes, and the blended number pointed at neither.

It surfaced sideways, from building a diagnostic (`evals/diagnose_abstains.py`) that disagreed with the report it was diagnosing — and the disagreement turned out to be the report's, not the diagnostic's. Both now call one shared `evals/abstain_scoring.py`, so they can't drift apart again, and every precision figure is printed next to its coverage and next to that 33.0% baseline, permanently. Full write-up in `DECISIONS.md`.

## Roadmap

- [x] **Phase 0 — Scaffold.** Project layout, tooling, CI-ready lint/test setup.
- [x] **Phase 1 — Data.** SEC EDGAR ingestion into DuckDB, analyst-facing schema, sanity queries against known filings.
- [x] **Phase 2 — Naive text-to-SQL.** End-to-end generation and execution baseline, no guardrails. 58.0% execution accuracy, 32.5% hallucinated-number rate on 103 gold cases — the "before" number Phase 3's guardrails are measured against.
- [x] **Phase 3 — Guardrails + audit.** AST-level SQL validation (sqlglot), live schema allowlisting, cost caps, a soft LLM scope prefilter, and a full JSONL audit trail on every request. 58.0% execution accuracy (unchanged from Phase 2 — guardrails don't cost correctness), 28.6% hallucinated-number rate, 88.9% (8/9) adversarial guardrail catch rate (see `DECISIONS.md` for the one documented miss) — see `reports/baseline.md`.
- [x] **Phase 4 — Hallucination detection.** Self-consistency voting (N=5, clustered by result values), grounded-answer generation (the model never sees the original question), a numeric + fiscal-year verifier, and a confidence-based abstain policy. 54.0% execution accuracy (vs Phase 3's 58.0%), 0.0% hallucinated-number rate (the primary target — met), 27.1% abstain precision (target ≥80%, not met; root-caused and documented in `DECISIONS.md` — mostly structurally unreachable under this phase's reduced scope or genuine small-model limitations the verifier correctly catches) — see `reports/eval.md`.
- [ ] **Phase 5 — Scale-out evals.** Larger model comparison on GPU infrastructure (**done**: real PSC Bridges-2/H100 comparison of `Qwen2.5-Coder-32B-Instruct-AWQ` and `Qwen3-Coder-30B-A3B-Instruct` via vLLM against the local `qwen2.5-coder:7b` baseline — same-family scale alone didn't help, a newer full-precision model reached 62.0% execution accuracy at 0.0% hallucinated-number rate; abstain precision barely moved either way, 27-29% across all three; see `DECISIONS.md` and `reports/phase5_model_comparison.md`), expanded gold set (**not started** — log-mining real questions from the audit trail, drafting gold SQL with the strong model, review queue; planned as a separate follow-up).
- [ ] **Phase 6 — Fine-tuning (stretch).** LoRA fine-tune of the local generation model on the gold set.
- [ ] **Phase 7 — Portfolio polish.** Metrics table, ablations, demo, tagged release.

## License

MIT — see [LICENSE](./LICENSE).
