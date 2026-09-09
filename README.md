# LedgerQL

An auditable natural-language-to-SQL system for financial data — layered guardrails, hallucination detection, and a full audit trail on every query. Runs entirely on local, open-weight models. No hosted LLM APIs, no cloud bill.

> Ask a plain-English question about company financials. LedgerQL returns a correct SQL query, the executed result, and a grounded answer with a confidence score — **or it refuses**, with a reason. It never returns a fabricated number.

**Status:** Phase 1 complete — 500 S&P constituents' 10-K filings loaded into DuckDB. Phase 2 (naive text-to-SQL baseline) is built and pending merge.

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

## Roadmap

- [x] **Phase 0 — Scaffold.** Project layout, tooling, CI-ready lint/test setup.
- [x] **Phase 1 — Data.** SEC EDGAR ingestion into DuckDB, analyst-facing schema, sanity queries against known filings.
- [ ] **Phase 2 — Naive text-to-SQL.** End-to-end generation and execution baseline, no guardrails. Built on `phase2-naive-sql`, pending merge: 58.0% execution accuracy, 32.5% hallucinated-number rate on 103 gold cases (see `reports/baseline.md` on that branch) — this is the "before" number the guardrails in Phase 3/4 are measured against.
- [ ] **Phase 3 — Guardrails + audit.** AST-level SQL validation, schema enforcement, full audit trail.
- [ ] **Phase 4 — Hallucination detection.** Self-consistency voting, grounded-answer verification, confidence scoring, abstain policy.
- [ ] **Phase 5 — Scale-out evals.** Larger model comparison on GPU infrastructure, expanded gold set.
- [ ] **Phase 6 — Fine-tuning (stretch).** LoRA fine-tune of the local generation model on the gold set.
- [ ] **Phase 7 — Portfolio polish.** Metrics table, ablations, demo, tagged release.

## License

MIT — see [LICENSE](./LICENSE).
