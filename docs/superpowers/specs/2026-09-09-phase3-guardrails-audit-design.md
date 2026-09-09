# Phase 3 — Guardrails + Audit: Design Spec

Status: approved, pending implementation plan.
Scope: LEDGERQL_MASTER_PROMPT.md Phase 3 acceptance criteria — Layers 1,
4, 5, 8 from the architecture (§5). Layer 5 (read-only, timed-out
execution) is already built in `ledgerql/execute.py` from Phase 2 and
needs no changes. This phase adds `classify.py` (Layer 1), `guardrails.py`
(Layer 4), and `audit.py` (Layer 8), and rewires `pipeline.py` to use all
three. Acceptance: 100% of adversarial gold cases blocked with the
correct reason code; every request produces a complete audit record;
each guardrail is independently tested.

## 1. Why this phase looks the way it does

The gold set (`evals/gold.jsonl`) was written before this phase, and it
already fixes more of the design than the master prompt states outright:

- `guardrail_must_fire` uses exactly four values across the whole set:
  `read_only`, `single_statement`, `schema_allowlist`, `cost_limit` (plus
  `None`, meaning "any mechanism that lands on the right reason code is
  fine"). `guardrails.py` adopts these as its guardrail-event vocabulary
  verbatim, so the eval scorer (§5) can assert on them directly instead
  of inventing a second taxonomy.
- The adversarial/schema_bait/out_of_scope tiers split into two distinct
  "no"s: `OUT_OF_SCOPE` (not a financial-data question at all — a stock
  prediction, an opinion, a poem, a DML request, a prompt injection) and
  `SCHEMA_MISMATCH` (a real financial-data question, but for a metric
  this schema doesn't have — dividend yield, employee count, credit
  rating). Both need `classify.py` to be able to emit either verdict, not
  just a scope boolean.
- `AMBIGUOUS`/`NO_DATA` cases exist in the gold set (ambiguous/time
  tiers) but are **not** in this phase's acceptance criterion (only
  "adversarial gold cases" are required to be blocked). Those reason
  codes belong to Phase 4's abstain-on-low-confidence policy — a
  genuinely ambiguous-but-in-scope-and-schema-valid question isn't
  something a static guardrail can catch; it needs the self-consistency/
  confidence machinery Phase 4 builds. Out of scope here.

## 2. `ledgerql/classify.py` (Layer 1) — soft prefilter, not the safety boundary

`classify(question: str, client: ollama.Client | None = None) ->
ClassifyResult` (new dataclass: `verdict: Literal["IN_SCOPE",
"OUT_OF_SCOPE", "SCHEMA_MISMATCH"]`, `explanation: str`).

A single Ollama call (same model/temperature/seed pattern as
`generate.py`), given the question and a short, fixed description of
what this schema *can* answer (S&P 500 constituents' 10-K annual
figures: revenue, net income, total assets, cash, plus whatever
`financial_facts` covers by tag — not a full schema dump, just enough
for the model to judge feasibility; the full schema context is Layer
2's job for cases that pass through). Few-shot examples drawn directly
from the gold set's own `O0x`/`H0x`/`S0x` cases, covering both negative
verdicts and a couple of `IN_SCOPE` examples so the model doesn't
over-refuse.

This is explicitly a **soft** filter: it saves a wasted generation call
on the clear-cut cases (predictions, opinions, creative writing, obvious
schema gaps) but it is allowed to be wrong. Nothing downstream trusts its
verdict as a safety guarantee — Layer 4 is the hard backstop for
anything Layer 1 lets through incorrectly (e.g. it says `IN_SCOPE` but
generation still hallucinates a column; `guardrails.py` catches that
structurally regardless of what classify said).

Pipeline behavior: `verdict != "IN_SCOPE"` short-circuits to an ABSTAIN
result with that verdict as the reason code, before schema retrieval or
generation ever run, and writes the audit record on that path too.

## 3. `ledgerql/guardrails.py` (Layer 4) — structural, sqlglot-based, the actual safety boundary

`validate(sql: str, db_path: str = execute.DB_PATH) -> GuardrailResult`
(new dataclass: `ok: bool`, `sql: str` — the re-emitted, comment-free SQL
if `ok`, else the original; `events: list[str]` — guardrail tags that
fired, using the four-value vocabulary from §1; `reason_code: str |
None`). Opens and closes its own short-lived connection internally for
the live column introspection (check 3 below), exactly mirroring
`execute.py`'s self-contained open/close-per-call pattern — with the
**same** `config={"enable_external_access": "false"}` execute.py uses.
Per today's actual incident (see `DECISIONS.md`,
"DuckDB connections to the same file must share config"), any two
connections to the same file need matching config, and a function that
owns its own connection start-to-finish is simpler to keep consistent
than threading a shared connection through pipeline.py across two
call sites.

Checks, in order, short-circuiting on the first hard failure:

1. **Parse.** `sqlglot.parse(sql, read="duckdb")`. Parse failure →
   `reason_code=EXEC_ERROR` (never reached the DB; this is the most
   honest existing code for "couldn't even validate it" — no new reason
   code is introduced since the master prompt fixes the six-value set in
   §6).
2. **Single SELECT.** Exactly one statement, top-level node is `exp.Select`
   (mirrors `evals/validate_gold.py`'s existing
   `check_single_select_and_tables` logic, reused directly rather than
   re-implemented — that function already does exactly this check and
   currently lives in a script instead of an importable module; it moves
   into `guardrails.py`'s single-statement check and
   `validate_gold.py` imports it back, so there is one implementation,
   not two). Failure → `events=["single_statement"]` or `["read_only"]`
   depending on which the offending statement type is (DML/DDL/PRAGMA/
   ATTACH → `read_only`; multiple statements via `;` → `single_statement`),
   `reason_code=OUT_OF_SCOPE` (matches every gold case in this bucket).
3. **Table/column allowlist.** Tables: same seven objects as
   `validate_gold.py`'s `ALLOWED_TABLES`. Columns: every `exp.Column`
   node's name must appear in the **live-introspected** column set for
   those seven objects (`SELECT table_name, column_name FROM
   information_schema.columns WHERE table_name IN (...)`, queried once
   per `validate()` call against the same connection `execute.py` would
   use — not hand-duplicated from `docs/schema.md`, which is exactly the
   two-sources-of-truth pattern that caused both of today's real bugs).
   This is a flat-set membership check, not full per-table alias
   resolution (a column valid on table A but wrongly referenced through
   table B's alias would slip through) — a known, documented
   simplification; full resolution would need to track each column
   reference back to its resolved table through joins/aliases, which
   sqlglot can do but isn't needed to catch any case in the current gold
   set (every schema_bait case invents a column that doesn't exist on
   *any* allowlisted object). Failure → `events=["schema_allowlist"]`,
   `reason_code=SCHEMA_MISMATCH`.
4. **Cost cap.** If the query has no `LIMIT` and no top-level aggregate
   (`COUNT`/`SUM`/`AVG`/`MIN`/`MAX`/`GROUP BY`), inject `LIMIT
   <LEDGERQL_ROW_LIMIT>` into the AST (reusing the existing env var from
   `execute.py`) rather than hard-refusing — S08's `accept_alternatives`
   explicitly rewards "answer with an enforced LIMIT and a note", and
   `execute.py` already threads a `truncated` flag through to
   `answer.py`'s prompt from Phase 2, so this is a two-line change, not
   new plumbing. `events` gets `"cost_limit"` appended (soft — doesn't
   set `ok=False` or a `reason_code`; the query still executes). This
   means S08 specifically will *answer* rather than *block* — the gold
   set's own `accept_alternatives` for S08 says exactly this scores full
   marks ("ANSWER with an enforced LIMIT and a statement that the full
   table is large and was truncated"), so it doesn't contradict the
   phase's "100% of adversarial cases blocked" criterion, it's the one
   case the gold set itself carves out as "either outcome is correct."
5. **Comment stripping.** Re-emit the AST via `.sql(dialect="duckdb")`
   before returning — sqlglot's pretty-printer doesn't preserve source
   comments, so this satisfies S10 ("contain no comments") as a side
   effect of the round-trip, not a dedicated check.

`validate_gold.py`'s import of the shared single-statement/table-allowlist
logic (point 2 above) is the one piece of `evals/` this phase touches;
everything else about the gold set stays frozen.

## 4. `ledgerql/audit.py` (Layer 8)

`write_record(record: dict) -> str` (returns a uuid4 id). Appends one
JSON line to `logs/audit.jsonl` (new `logs/` directory, gitignored like
`reports/*.jsonl` — this is runtime output, not source). No live table,
no migrations, per your call: JSONL is the source of truth, and it's
already directly queryable from DuckDB on demand (`SELECT * FROM
read_json_auto('logs/audit.jsonl')`) whenever Phase 5's log-mining needs
it — no loader script required now.

Record shape (every field constraint #4 requires): `id`, `timestamp`,
`question`, `classify_verdict`, `classify_explanation`, `generated_sql`,
`guardrail_events`, `guardrail_reason_code`, `execution_summary` (columns,
row count, `truncated`, `error` — a summary per the constraint's own
wording, not a full row dump), `answer`, `confidence: null` (Phase 4
populates this; the field exists now so Phase 4 doesn't need another
pipeline rewiring), `reason_code` (the final, top-level abstain reason if
any), `latency_ms`.

Written on **every** exit path — classify short-circuit, guardrail
short-circuit, execution error, and success — via a single call site at
the end of `pipeline.ask()` (a `try/finally`-shaped structure, not one
`write_record` call duplicated at each early return).

## 5. `pipeline.py` rewiring

```
verdict, explanation = classify.classify(question)
if verdict != "IN_SCOPE":
    result = {..., "answer": None, "reason_code": verdict}
else:
    schema_context = schema_index.get_schema_context()
    sql = generate.generate_candidates(question, schema_context, n=1)[0]
    guard = guardrails.validate(sql, db_path=db_path)
    if not guard.ok:
        result = {..., "sql": sql, "answer": None, "reason_code": guard.reason_code}
    else:
        exec_result = execute.execute(guard.sql, db_path=db_path)
        if exec_result.error:
            result = {..., "reason_code": "EXEC_ERROR", "answer": None}
        else:
            answer_text = answer.write_answer(question, exec_result)
            result = {..., "reason_code": None, "answer": answer_text}
audit.write_record({...result, "latency_ms": ...})
return result
```

`db_path` threading (added in the post-merge fix wave) is preserved
unchanged. `n=1` generation stays as-is — self-consistency is Phase 4.

## 6. Eval scoring extension

`evals/run_eval.py` currently scores only the 50 `ANSWER`-expected cases
and treats the other 53 descriptively. This phase adds real scoring for
the adversarial/schema_bait/out_of_scope tiers (the ones this phase's
acceptance criterion is actually about):

- Pipeline returned `ABSTAIN` (i.e. `answer is None` with a
  `reason_code`) and that code matches `expected` case's `reason_code`
  (or is listed in `accept_alternatives`) → pass.
- When `guardrail_must_fire` is set, the audit record's `guardrail_events`
  for that case must contain that tag → pass/fail contributes to a new
  **guardrail catch rate** metric, reported per the four tags.
- `reports/baseline.md` gains a new section: guardrail catch rate
  (adversarial tier, target 100% per the acceptance criterion) and
  reason-code accuracy, alongside the existing execution-accuracy/
  hallucination-rate numbers from Phase 2 (which stay as the frozen
  "before" — this phase's report becomes the "guardrails on" comparison
  row `evals/README.md` §5's ablation table already expects).

## 7. Testing

Per the acceptance criterion ("tests cover each guardrail
independently"): each of the five `guardrails.validate()` checks gets a
direct unit test with a hand-written SQL string (temp-file DuckDB
fixture, same pattern as `tests/test_execute.py`) — no Ollama, no
pipeline, no gold set involved. `classify.py` gets unit tests with a
fake Ollama client (same pattern as `tests/test_generate.py`) covering
one example of each verdict. `audit.py` gets a unit test asserting a
written record round-trips through `read_json_auto` with all required
fields present. `pipeline.py` gets tests for each short-circuit path
(classify rejects, guardrail rejects, execution errors, success) with
all three dependencies faked, matching `tests/test_pipeline.py`'s
existing style. The real, scored acceptance check (100% adversarial
catch rate) runs via `make baseline` against the live Ollama model, same
as Phase 2's baseline — not a unit test, since it depends on real model
behavior.

## 8. Out of scope for this spec

- `consensus.py`, `verify.py` (Phase 4) — no self-consistency voting, no
  grounded-answer numeric verifier, no real confidence score yet
  (`audit.py` records `confidence: null`).
- The FastAPI/Streamlit surface — still not named in any phase's
  acceptance criteria through Phase 3; `GET /audit/{id}` becomes trivial
  once it's built (read one JSONL line by id), but building it isn't
  this phase's job.
- Any change to `docs/schema.md`, `ledgerql/data/*`, or `evals/gold.jsonl`
  content (the shared single-statement/table-allowlist logic moving from
  `validate_gold.py` into `guardrails.py`, §3, is a refactor of
  validation code, not a change to the gold data itself).
- `AMBIGUOUS`/`NO_DATA` handling (§1) — Phase 4's abstain policy.
