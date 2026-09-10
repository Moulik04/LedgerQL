# Phase 4 — Hallucination Detection: Design Spec

Status: approved, pending implementation plan.
Scope: LEDGERQL_MASTER_PROMPT.md Phase 4 acceptance criteria — Layers 6
(self-consistency) and 7 (grounded answer + numeric verifier), confidence
scoring, an abstain policy. Acceptance: hallucinated-number rate on the
eval set is 0; abstain precision ≥ 0.8; a full ablation table produced by
`make eval`.

## 1. Why this phase looks the way it does

`evals/README.md` §4-§7 describes a considerably larger calibration
framework than the master prompt's own Phase 4 acceptance criteria ask
for: a calib/test split, a fitted logistic-regression confidence model
on five signals, reliability diagrams, ECE/MCE/Brier decomposition,
AURC, and twin-consistency checks. Per explicit direction, this phase
builds only what the master prompt's acceptance criteria require —
self-consistency voting, grounded-answer generation, a numeric verifier,
a simple (not statistically fitted) confidence score, and an abstain
threshold picked empirically against the real gold set (same methodology
already used successfully this session for `classify.py`'s prompt
design) rather than via a formal calib/test sweep. The full calibration
framework in §6 stays explicitly out of scope, for a later phase.

`ledgerql/consensus.py` and `ledgerql/verify.py` already exist as Phase 0
stubs (`NotImplementedError("Phase 4")`) with docstrings that already
describe almost exactly this design — this spec fills them in, it
doesn't redesign the module boundaries the project already committed to.

## 2. Verified facts this spec depends on

Confirmed directly against the real environment during brainstorming, not
assumed:

- **`OLLAMA_TEMPERATURE=0.2` (the existing single-shot default) produces
  near-useless sample diversity for self-consistency.** Generating 5
  candidates for a real gold-set aggregation question
  (`"What was the average revenue across companies in the Information
  Technology sector in fiscal 2024?"`) at temperature 0.2 with 5
  different seeds produced 4 byte-identical candidates and 1 outlier —
  not a meaningful agreement signal, since near-total convergence would
  happen regardless of whether the question was actually easy or hard.
  At `temperature=0.7`, the same question produced genuinely different
  candidates (one correctly joining `companies` for `gics_sector`, one
  incorrectly assuming that column lives on `v_revenue` directly) —
  while an unambiguous lookup ("Apple's revenue in fiscal 2024") still
  converged 5/5 to the identical, correct query at the same temperature.
  This is the signal self-consistency needs: agreement tracking real
  difficulty, not sampling noise. New env var: `OLLAMA_CONSENSUS_TEMPERATURE`,
  default `0.7`, used only for the N-candidate generation step.
- **Known, accepted limitation, verified not engineered around:** on a
  fully unspecified question ("What was the revenue?" — no company, no
  year), temperature 0.7 across 5 seeds did *not* show strong
  disagreement — 4/5 samples confidently defaulted to the same guess
  ("Apple", fiscal 2024). Self-consistency catches "the model is
  genuinely torn between interpretations," not "the model confidently
  guessed a default no one asked for." This is a real gap for the
  `ambiguous` gold tier specifically, not something this phase's
  acceptance criteria (hallucinated-number rate, adversarial-adjacent
  abstain precision) are measured on — documented here rather than
  chased with more prompt engineering.
- **`extract_numbers()` and `_scalar_match()` already exist, tested, in
  `evals/run_eval.py`** (lines 38-83) — the regex-based number extractor
  (handles magnitude words, comma-formatted numbers, percent signs,
  excludes bare years and SEC form codes) and the tolerance-based scalar
  comparator. Both get reused, not reimplemented.
- **DuckDB rows can carry a magnitude mismatch that the existing
  `extract_numbers()` + tolerance-match mechanism already catches for
  free:** if an answer states a number with the wrong magnitude word
  (e.g. "$391.0 million" for a value that's actually ~$391 billion),
  `extract_numbers()`'s magnitude-word scaling reconstructs a claimed
  raw value (391,000,000) wildly different from the grounded raw value
  (~391,035,000,000) — a ~1000x gap that fails even a loose relative
  tolerance. No separate "unit consistency" mechanism is needed for
  magnitude-word errors specifically; the numeric verifier already
  covers this case as a side effect of what it already checks.
- **Fiscal-year correctness is *not* covered by the above**, and needs
  its own check: `extract_numbers()` deliberately *excludes* bare
  4-digit years (2000-2099) from the hallucination check, since years
  appear constantly in correct, grounded answers ("fiscal year 2024")
  and aren't data values in the tolerance-match sense. This means a
  wrong fiscal year stated in an answer currently passes the numeric
  verifier silently. `unit_period` (8 gold cases: "billions/millions
  scaling, fiscal-vs-calendar-year, NULL `fiscal_period` on non-10-K
  forms") specifically tests this, and the master prompt's own
  hallucination-detection table lists "Unit/period check" as a named
  layer — this is core, not an extra. `verify.py` adds a distinct,
  narrow fiscal-year consistency check (§5) alongside the numeric one.

## 3. `ledgerql/generate.py` — lift the `n=1` restriction

`generate_candidates(question, schema_context, n=1, client=None)`
currently raises `NotImplementedError` for any `n != 1`. This phase:

- Removes that restriction — `n` becomes a real parameter.
- Adds a `temperature: float | None = None` parameter, defaulting to
  the module's existing `OLLAMA_TEMPERATURE` (0.2) when not given, so
  every existing single-shot call site (unaffected by this phase) keeps
  its current behavior unchanged.
- For `n > 1`, the caller (`pipeline.py`, §6) passes
  `temperature=OLLAMA_CONSENSUS_TEMPERATURE` explicitly and makes `n`
  separate calls, each with a different seed: `seed = OLLAMA_SEED + i`
  for `i in range(n)` — keeps the whole N-candidate batch reproducible
  run-to-run (same 5 seeds every time) while giving each call a real
  chance at a different sampling path. `generate_candidates` itself
  loops internally and returns `list[str]` of length `n`, same return
  shape as today (today's `n=1` path is just the `n=1` case of the same
  loop).

## 4. `ledgerql/consensus.py` — self-consistency vote

New shape (the Phase 0 stub's `vote(results: list) -> None` signature
was a placeholder, not a locked interface):

```
@dataclass
class ConsensusResult:
    sql: str | None          # winning candidate's SQL (re-emitted, guardrail-validated form)
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    agreement: float         # winning cluster size / N (N = total candidates requested, not just survivors)
    events: list[str]        # every surviving candidate's guardrail events, deduplicated
    reason_code: str | None  # set only when there is no usable winner
    detail: str | None

def vote(guards: list[GuardrailResult], executions: list[ExecutionResult | None]) -> ConsensusResult
```

Given `N` generated SQL strings, the caller (`pipeline.py`) has already
run each through `guardrails.validate()` (`guards`, always length `N`,
never `None`) and, for every one that passed, `execute.execute()`
(`executions`, same length, `None` at index `i` whenever `guards[i].ok`
is `False`). `vote()`:

1. Clusters the *successful* executions by `(tuple(columns), frozenset of row tuples)`
   equality — a result set, not raw SQL text, is what "agreement" means
   (two differently-worded but semantically-equivalent queries should
   count as agreeing).
2. The largest cluster wins. `agreement = len(winning cluster) / N` —
   deliberately divided by the *total* requested sample count, not just
   the count that executed successfully, so a case where only 2 of 5
   candidates even produced valid SQL is scored as 2/5 = 0.4 agreement,
   not 2/2 = 1.0 — a low success rate is itself a low-confidence signal
   and must not be hidden by only comparing survivors to each other.
3. If there is no winning cluster (every candidate was rejected or
   errored — `N` `None` executions), `reason_code` is set from the most
   common guardrail `reason_code` among the `N` rejections (mode; ties
   broken by first occurrence) — mirrors Phase 3's single-shot behavior
   for adversarial cases, now robust to the rare case where the model's
   samples disagree even about *why* a request is bad. `reason_code`
   stays `None` whenever a winning cluster *was* found, **even if that
   winner's own `rows` is legitimately empty** (a real "no matching
   data" result is a successful consensus, not a failure to reach one —
   `reason_code is None` is the caller's signal that a winner exists,
   never "and `rows` is non-empty").
4. Ties between two equally-sized clusters: the earliest-generated
   candidate (lowest seed) wins arbitrarily — documented as an accepted
   simplification, not a scored behavior any gold case depends on.

## 5. `ledgerql/verify.py` — numeric + fiscal-year grounding

```
@dataclass
class VerifyResult:
    ok: bool
    ungrounded_numbers: list[float]
    detail: str | None

def verify(answer: str, columns: list[str], rows: list[tuple]) -> VerifyResult
```

Two checks, both against the winning `ConsensusResult`'s own
`columns`/`rows` (never the gold set — this is runtime grounding, not
eval scoring):

1. **Numeric grounding** (reuses `extract_numbers()`, moved here as the
   canonical version — see §7): every number `extract_numbers(answer)`
   returns must scalar-match (loose relative tolerance, reusing the
   existing `_scalar_match` pattern at 1% tolerance) at least one
   `int`/`float` value across all `rows`. Any that doesn't → `ok=False`,
   collected into `ungrounded_numbers`.
2. **Fiscal-year grounding** (new, narrow, per §2's verified gap): if
   `"fiscal_year"` is one of `columns`, extract bare 4-digit years
   (2000-2099) mentioned in `answer` (a separate, deliberately simple
   regex — reusing `_YEAR_RE`'s pattern, not `extract_numbers`, since
   that function explicitly excludes years) and confirm each one appears
   in the `fiscal_year` column's actual values across `rows`. A
   mismatched year → `ok=False`, same `ungrounded_numbers` list (a wrong
   year is exactly as much a hallucinated number as a wrong dollar
   figure, from the caller's perspective).

`verify()` never touches units/magnitude words directly — §2 already
established `extract_numbers()`'s existing magnitude-word reconstruction
catches that class of error as a side effect of check 1.

## 6. `ledgerql/answer.py` — hide the question

Per your explicit direction: the answer-writing prompt shows only the
column names and result rows — never the original natural-language
question, never the SQL. `write_answer(result: ExecutionResult, client=None) -> str`
— **signature change**, `question` parameter removed (every call site
in `pipeline.py` updates accordingly). New system prompt:

> "Write one or two plain-English sentences describing the data in this
> table. Use only the values shown — do not add, round differently, or
> infer any number not present. State any unit or fiscal year exactly as
> given."

The empty-result case (`result.rows == []`) keeps today's behavior
(`(no rows)` in the formatted table, the model asked to say so) —
unaffected by hiding the question, since that branch already doesn't
depend on the question's content.

## 7. `evals/run_eval.py` — DRY the number extractor, wire in confidence/abstain scoring

- `extract_numbers()`, `_MAGNITUDE`, `_NUMBER_RE`, `_YEAR_RE`,
  `_FORM_CODE_RE` move into `ledgerql/verify.py` as the canonical
  implementation (module-level, not underscore-prefixed there, since
  it's now a shared public function — `verify.extract_numbers`).
  `run_eval.py` imports it back (`from ledgerql.verify import
  extract_numbers`) for its own hallucination-number-rate metric, which
  stays a useful independent eval-level audit even though `verify.py`
  now also runs the identical check inside the live pipeline — this
  mirrors Phase 3's `guardrails.py`/`validate_gold.py` extraction
  exactly, avoiding a third copy of logic that has already caused two
  real bugs in this project's history (see `DECISIONS.md`).
- `pipeline.ask()`'s result dict gains `confidence: float | None` — no
  longer always `null` in the audit record; populated from
  `ConsensusResult.agreement` whenever a consensus was actually reached
  (`None` when short-circuited before generation, matching today's
  behavior for classify/guardrail-rejected paths, which have no
  meaningful agreement signal).
- `evals/run_eval.py` needs a real **abstain precision** metric now that
  there's a genuine abstain policy (Phase 3 only had static guardrails +
  classify, both deterministic; Phase 4 adds a probabilistic one). Add:
  `abstain_precision = correct_abstains / all_abstains` and
  `abstain_recall = correct_abstains / expected_abstains`, computed
  across all `ABSTAIN`/`ANSWER_WITH_ASSUMPTION`-expected cases (not just
  the three static-guardrail tiers Phase 3 scored) — "correct" meaning
  the case abstained AND the reason code matches (or is in
  `accept_alternatives`, same caveat as Phase 3's `score_guardrail_case`
  — free-text `accept_alternatives` parsing stays out of scope, same
  reasoning as the parked Phase 3 finding).
- The eval report (`reports/eval_<date>.md` per §9's decision) gains the
  ablation table `evals/README.md` §5 already specifies:
  `naive (Phase 2)` → `+static guardrails (Phase 3)` → `+self-consistency
  & verifier (Phase 4)`, using the three phases' already-committed real
  numbers (Phase 2: 58.0%/32.5%, Phase 3: 58.0%/28.6%/88.9% adversarial
  catch, both already in git history) plus this phase's new run.

## 8. `ledgerql/pipeline.py` — orchestration changes

```
classify → (short-circuit as today)
schema_index.get_schema_context()
sqls = generate.generate_candidates(question, schema_context, n=5, temperature=OLLAMA_CONSENSUS_TEMPERATURE)
guards = [guardrails.validate(sql, db_path=...) for sql in sqls]
execs = [execute.execute(g.sql, db_path=...) if g.ok else None for g in guards]
consensus_result = consensus.vote(guards, execs)

# Two distinct, independent abstain triggers -- not one combined check:
if consensus_result.reason_code is not None:
    -> abstain, reason_code = consensus_result.reason_code          # no winning cluster at all
elif consensus_result.agreement < LOW_AGREEMENT_THRESHOLD:
    -> abstain, reason_code = "LOW_AGREEMENT"                        # a winner exists, but weakly
# otherwise: a winner exists with sufficient agreement, even if its
# own rows are legitimately empty (a real "no data" result) -- proceed.

answer_text = answer.write_answer(consensus_result)  # question hidden
verify_result = verify.verify(answer_text, consensus_result.columns, consensus_result.rows)
if not verify_result.ok:
    -> abstain, reason_code = "UNGROUNDED_ANSWER"
else:
    -> success, confidence = consensus_result.agreement
```

`_finish()` (the single audit-write helper from Phase 3) gains a
`confidence` parameter, threaded into both the returned dict and the
audit record in place of the hardcoded `None`. The existing
`try/except Exception` catch-all around the whole `ask()` body (Phase
3's final-review fix) already covers every new failure mode here (a
`generate_candidates` exception, a `consensus.vote` bug, etc.) without
changes.

**Abstain threshold:** picked empirically during planning/implementation
against the real gold set (`ambiguous`, `time`, and the `ANSWER`-tier
cases as a false-positive check) — not a hardcoded guess in this spec.
The plan will run a small sweep (e.g. 0.4, 0.6, 0.8) against real
pipeline output and document which value was chosen and why, same
methodology as `classify.py`'s prompt tuning this session.

## 9. Report naming

`reports/baseline.md` is Phase 2/3's name for the "no abstain policy
yet" report. Phase 4 introduces a genuinely different eval — one with
an abstain policy, confidence, and an ablation table across all three
phases. **Decision:** switch to `reports/eval_<date>.md`, written by a
real `make eval` target, retiring `make baseline`. The Makefile's
existing `eval:` target is a stale Phase 0 placeholder pointing at a
nonexistent module (`ledgerql.eval.run`, per Phase 2's plan notes) — this
phase finally gives it a real implementation rather than adding a fourth
report name to the project's history. Phase 4 is the first phase where
"eval" (scored, an abstain policy, confidence) is a more honest word than
"baseline" (unscored naive run) for what's being produced. The
ablation ladder should still show Phase 2 and Phase 3's real historical
numbers, not just this phase's.

## 10. Out of scope for this spec

- The full calibration framework: calib/test split, fitted logistic
  regression confidence, reliability diagrams, ECE/MCE/Brier, AURC,
  twin-consistency checks (`evals/README.md` §4/§6) — explicitly
  deferred to a later phase per your direction (§1).
- `accept_alternatives` free-text parsing in eval scoring — same parked
  reasoning as Phase 3's `S03` finding, still applies.
- The `ambiguous`-tier "confident default guess" gap identified in §2 —
  documented, not engineered around, since it isn't what this phase's
  acceptance criteria measure.
- The FastAPI/Streamlit surface — still not named in any phase's
  acceptance criteria through Phase 4.
- Any change to `docs/schema.md`, `evals/gold.jsonl`, `ledgerql/data/*`,
  `ledgerql/guardrails.py`, `ledgerql/classify.py`, or `ledgerql/audit.py`'s
  own `write_record()` mechanism (only its call site in `pipeline.py`
  gains a new field) — all frozen/complete from prior phases.
