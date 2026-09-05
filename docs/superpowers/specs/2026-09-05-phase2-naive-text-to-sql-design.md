# Phase 2 — Naive Text-to-SQL: Design Spec

Status: approved, pending implementation plan.
Scope: LEDGERQL_MASTER_PROMPT.md Phase 2 acceptance criteria — Ollama
generation with schema in prompt, execution, a raw (unguardrailed)
answer — run end to end and a baseline accuracy number recorded in
`reports/baseline.md`. Phase 1's schema-expansion detour is explicitly
abandoned; this phase builds against the real, merged Phase 1 schema
(`docs/schema.md`) and the now-fully-reconciled `evals/gold.jsonl`
(103 cases, `evals/validate_gold.py` passing clean).

## 1. Why this phase looks the way it does

The master prompt's Phase 2 acceptance criteria were written before
`evals/gold.jsonl` existed in its current form (103 hand-written cases
across 12 tiers, with a full scoring rubric in `evals/README.md`). This
spec supersedes "20 gold questions" with the real set — see §5.
Everything else in Phase 2's scope (no guardrails, no self-consistency,
no grounded-answer verification) is unchanged from the master prompt:
those are Phase 3 and Phase 4's jobs respectively, and `evals/README.md`
§5's own ablation table (`naive (Phase 2) -> +static guardrails ->
+self-consistency -> +grounded answer & verifier`) explicitly expects
Phase 2 to be the unguarded "before" row.

## 2. Ollama configuration

- Model: `qwen2.5-coder:7b` (already pulled locally, already the
  `.env.example` default via `OLLAMA_MODEL`).
- Temperature: `> 0` (matching the master prompt's general architecture
  description literally), **paired with a fixed seed** so
  `reports/baseline.md` stays reproducible run-to-run despite the
  non-zero temperature — Ollama's `/api/generate` accepts both
  `temperature` and `seed` in its `options` object. New env vars:
  `OLLAMA_TEMPERATURE=0.2`, `OLLAMA_SEED=42`.
- `OLLAMA_HOST` (already in `.env.example`) is used as-is.

## 3. Modules

### `ledgerql/schema_index.py`

Per Phase 1 brainstorm decision: reuse `docs/schema.md` directly rather
than maintaining a second hand-tuned schema format. `get_schema_context()
-> str` reads `docs/schema.md` and strips it down to the parts useful in
a generation prompt: table/view definitions and column tables, dropping
narrative sections (Known gap prose, the dual-class note, example SQL)
that don't help the model produce correct SQL and just cost tokens. This
is a fixed, static transform — no per-question retrieval logic yet
(schema is only 3 tables + 4 views; nothing to selectively retrieve).
Per-question retrieval is a natural Phase 5+ concern if the schema grows.

### `ledgerql/generate.py`

`generate_candidates(question: str, schema_context: str, n: int = 1) ->
list[str]`. For Phase 2, always called with `n=1` (per Phase 1-adjacent
brainstorm decision: single-shot baseline, not N-candidate-then-discard).
Builds a prompt instructing the model to return exactly one DuckDB
`SELECT` statement and nothing else, calls Ollama's `/api/generate` with
the schema context and question, strips markdown code fences from the
response (qwen2.5-coder reliably wraps SQL in ` ```sql ` fences even when
told not to — stripping is mechanical, not a guardrail), and returns the
raw SQL text unvalidated. No AST parsing, no schema-binding check, no
single-statement enforcement — that is Phase 3's `guardrails.py`.

### `ledgerql/execute.py`

`execute(sql: str, timeout_seconds: float | None = None) ->
ExecutionResult` (new dataclass: `columns: list[str]`, `rows: list[tuple]`,
`error: str | None`, `truncated: bool`).

Two safety behaviors that are **not** guardrails in the evaluative sense
(they don't validate, explain, or score anything — they're baseline
infrastructure hygiene, consistent with Phase 1's own read-only design
and the master prompt's non-negotiable constraint #3):

- Opens the DuckDB connection **read-only** (`duckdb.connect(db_path,
  read_only=True)`) always, every call. An adversarial prompt that gets
  the model to generate `DELETE`/`DROP`/`UPDATE` fails with a permission
  error, surfaced honestly as `error` — informative for the baseline
  report, not destructive to real data.
- Truncates the fetched result to `LEDGERQL_ROW_LIMIT` rows (env var,
  already defined, default 1000) client-side after execution, setting
  `truncated=True` if the cap was hit. This is a memory/context safety
  cap, not the cost-estimate-before-execution guardrail the master
  prompt's architecture stage 4 describes (that stays Phase 3's job).
- Enforces `timeout_seconds` (default from `LEDGERQL_QUERY_TIMEOUT_SECONDS`,
  already defined, default 10) via a background thread running the query
  and `con.interrupt()` if the thread doesn't finish in time — DuckDB
  connections support `.interrupt()` from another thread. A timeout is
  reported as `error`, not a crash.

### `ledgerql/answer.py`

Phase 0 left this stubbed for Phase 4's grounded-answer stage
(`write_answer(question, result_table) -> str`, deliberately hiding the
question from the model at that later stage to force grounding in data
alone). Phase 2 implements a Phase-2-appropriate version now: shows the
model **both** the question and the executed result table, asks for a
plain-English answer, returns it unverified. Phase 4 will change this
function's behavior substantially (hide the question, add the numeric
verifier) — that's expected, deliberate evolution, not a defect to avoid
by over-building Phase 2. The signature stays `write_answer(question:
str, result: ExecutionResult) -> str`.

If `execute()` returned an error, `write_answer` is not called — the
pipeline reports the execution error directly as the "answer" (there is
nothing to summarize).

### `ledgerql/pipeline.py`

`ask(question: str) -> dict` — replaces the Phase 0 stub's placeholder
signature (`-> dict`, unchanged) with real orchestration:

```
schema_context = schema_index.get_schema_context()
sql = generate.generate_candidates(question, schema_context, n=1)[0]
result = execute.execute(sql)
answer = answer.write_answer(question, result) if result.error is None else None
return {
    "question": question, "sql": sql, "columns": result.columns,
    "rows": result.rows, "truncated": result.truncated,
    "error": result.error, "answer": answer,
}
```

No `classify.py` call (Phase 3), no consensus/voting (Phase 4), no
confidence score, no abstain — Phase 2's pipeline attempts to answer
*every* question, including the adversarial/out-of-scope ones in
`gold.jsonl`. That is the intended, informative "before" behavior: the
eval harness (§5) will show exactly what a guardrail-free system does
with "Delete all filings for Tesla" or "Should I buy Tesla stock?", and
Phase 3/4's job is measurably improving on it.

## 4. Prompt design

Two prompts, both simple, both logged in full per query (master prompt
hard constraint #4 — every query is logged):

- **Generation prompt**: system-style instructions + the trimmed schema
  context (§3) + the question, asking for exactly one DuckDB `SELECT`
  statement, no prose, no markdown fences (fences get stripped
  mechanically regardless, since the model doesn't reliably comply).
- **Answer prompt**: the question + the executed result (as a small
  formatted table, capped by the same `LEDGERQL_ROW_LIMIT`), asking for a
  plain-English answer to the question using only that data.

## 5. Eval harness

New `evals/run_eval.py` (distinct from the user's `evals/validate_gold.py`,
which only checks that the *gold* SQL itself is valid — `run_eval.py`
actually runs the pipeline under test against each question and scores
it against gold).

- Runs against **all 103 cases** in `evals/gold.jsonl` (not a 20-question
  subset — see §1).
- Implements exactly two metrics from `evals/README.md` §5, the two that
  are meaningful without guardrails or calibration:
  - **Execution accuracy**: on the 50 `expected: "ANSWER"` cases only
    (matching the metric's own definition), execute `pipeline.ask()`'s
    generated SQL, compare its result to `gold_sql`'s executed result
    per the case's `compare` field (`scalar`/`set`/`ordered`/`empty`/
    `count`). This is new comparison logic in `run_eval.py`, not reused
    from `validate_gold.py` directly — `check_executes` there validates
    that a gold query's *own* result matches its declared shape (e.g.
    "scalar" means exactly 1x1), a different job from comparing two
    already-executed result sets (pipeline's vs. gold's) against each
    other. `run_eval.py`'s comparison function follows the same
    `compare`-field vocabulary for consistency of meaning (`scalar`/
    `scalar_or_null` compares one value with tolerance, `set` compares
    as an unordered collection of row-tuples, `ordered` compares as a
    sequence, `empty` requires both sides to have zero rows, `count`
    compares the single count value) but is its own implementation.
    Reported overall and per-tier.
  - **Hallucinated-number rate**: for every case where the pipeline
    produced a non-null `answer`, extract numbers from the answer text
    (regex over digit sequences, handling commas/decimals/`$`/`%`/
    magnitude words like "billion"/"million") and check each against the
    values actually present in that query's own executed result set
    (within a loose relative tolerance, to allow for stated rounding).
    Reported as a single rate across all cases with a non-null answer,
    not just the 50 `ANSWER` cases — Phase 2 has no abstain mechanism, so
    it will "answer" plenty of cases it shouldn't, and that is exactly
    what this number is meant to expose.
- The remaining 53 `ABSTAIN`/`ANSWER_WITH_ASSUMPTION` cases are **not**
  scored pass/fail (that requires guardrail/calibration concepts Phase 2
  doesn't have) but their outcomes are still recorded descriptively:
  how many did the naive pipeline "answer" anyway (expected — there's no
  abstain logic), how many errored out (e.g. the adversarial DML cases,
  which the read-only connection turns into permission-denied errors),
  broken down by tier.
- Explicitly **not** implemented in Phase 2 (all genuinely gated to later
  phases per `evals/README.md` §5-§6's own ablation framing): confidence
  scoring, the calib/test split, the deterministic-then-judge
  `answer_must_state` rubric grader, guardrail-specific checks
  (`guardrail_must_fire`, `executed_sql_must`), abstain precision/recall,
  reason-code accuracy, selective accuracy/AURC, calibration/reliability
  metrics.

### Makefile target

New `make baseline` target (not `make eval` — that name is reserved for
the fuller framework `evals/README.md` already documents, which needs
guardrails/self-consistency/confidence to produce a meaningful ablation
table; reusing the name early for a narrower Phase 2 script would leave
`make eval` referring to two different things across the project's
history). `make baseline` runs `evals/run_eval.py` and writes
`reports/baseline.md`.

## 6. `reports/baseline.md` contents

Per the master prompt: "This number becomes the 'before' in the README."
Contents:

- Overall execution accuracy (on the 50 `ANSWER` cases) and per-tier
  breakdown for tiers that contain `ANSWER` cases (lookup, aggregation,
  raw_facts, time, ratio, unit_period — the tiers with zero `ANSWER`
  cases, like adversarial/out_of_scope, are noted as "no positive control
  in this tier" rather than silently omitted).
- Hallucinated-number rate across all cases with a non-null answer.
- Descriptive summary of the 53 non-`ANSWER` cases: how many the naive
  pipeline attempted to answer anyway, how many errored (with a brief
  breakdown — e.g. "N adversarial cases errored with a read-only
  permission violation" is itself a meaningful, citable data point for
  the eventual guardrails-on/off story).
- Model, temperature, seed, and quarter-window/database-build date used,
  for reproducibility.
- Every individual case's generated SQL, execution result summary, and
  answer, logged to a companion `reports/baseline_<date>.jsonl` (one
  record per case) — mirrors the audit-log spirit of master prompt hard
  constraint #4 even though `audit.py` proper is Phase 3's job.

## 7. Out of scope for this spec

- `classify.py` (Phase 3), `guardrails.py` (Phase 3), `consensus.py`
  (Phase 4), `verify.py` (Phase 4), `audit.py` (Phase 3, though
  `reports/baseline_<date>.jsonl` above covers Phase 2's logging need
  informally in the meantime).
- The FastAPI/Streamlit surface (master prompt section 5) — Phase 2's
  acceptance criteria is a working pipeline and a baseline report, not a
  UI; the API/UI aren't named in Phase 2's acceptance criteria at all.
- Any change to `docs/schema.md`, `ledgerql/data/*`, or `evals/gold.jsonl`
  — those are frozen/complete per the user's explicit direction to leave
  Phase 1 as completed.
