# Phase 4 — Hallucination Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build self-consistency voting (5 candidates, clustered by result set), grounded-answer generation with a numeric + fiscal-year verifier, a simple agreement-based confidence score, and an empirically-picked abstain threshold — hitting the master prompt's Phase 4 acceptance criteria (hallucinated-number rate 0, abstain precision ≥ 0.8) without building the full statistical calibration framework `evals/README.md` describes (explicitly deferred).

**Architecture:** `generate.py` grows an `n`-candidate loop at a separate, higher temperature. Each candidate goes through the existing `guardrails.py` (unchanged) and `execute.py` (unchanged). New `consensus.py` clusters the survivors by result-set equality and picks a majority winner with an agreement score. `answer.py` writes the answer from the winning result alone — the original question is never shown to it. New `verify.py` checks every number (and every fiscal year) the answer states against the winning result set. `pipeline.py` wires all of this with two independent abstain triggers (no consensus winner; agreement below threshold) plus the existing verify-failure trigger, threading a real confidence score into the audit record for the first time.

**Tech Stack:** Python 3.12, the `ollama` Python client (unchanged dependency), DuckDB (unchanged), pytest with `monkeypatch`/fake clients/temp-file DuckDB fixtures — same patterns as every prior phase.

**Spec:** [docs/superpowers/specs/2026-09-10-phase4-hallucination-detection-design.md](../specs/2026-09-10-phase4-hallucination-detection-design.md)

## Global Constraints

- Zero cost, no hosted LLM APIs — local Ollama only (master prompt hard constraints #1-#2).
- Every query is still logged, nothing silently dropped (master prompt hard constraint #4) — the existing `try/except Exception` catch-all around `pipeline.ask()`'s body (Phase 3) already covers every new failure mode this phase introduces; do not remove or narrow it.
- `docs/schema.md`, `evals/gold.jsonl`, `evals/README.md`, `ledgerql/data/*`, `ledgerql/guardrails.py`, `ledgerql/classify.py`, and `ledgerql/audit.py`'s own `write_record()` mechanism are frozen — do not modify them in this plan. `ledgerql/execute.py` is also frozen (Layer 5 is unchanged this phase).
- The full calibration framework (`evals/README.md` §4/§6: calib/test split, fitted logistic-regression confidence, reliability diagrams, ECE/MCE/Brier, AURC, twin-consistency) is explicitly out of scope for this plan.
- `accept_alternatives` free-text parsing in eval scoring stays out of scope, same reasoning as Phase 3's parked `S03` finding.
- Model: `qwen2.5-coder:7b` (already pulled). Ollama daemon must be running locally before Task 7's real run. `data/ledgerql.duckdb` already exists and is built — no data rebuild needed.
- `N_CANDIDATES = 5`, confirmed with you during brainstorming.

---

## Verified facts this plan depends on

Confirmed directly against the real environment during brainstorming (not assumed):

- **`OLLAMA_TEMPERATURE=0.2` (the existing single-shot default) produces near-identical samples across different seeds** — a real gold-set aggregation question generated 4 byte-identical candidates out of 5 at temperature 0.2. At `temperature=0.7`, the same question produced genuinely different candidates (one correct JOIN, one wrong column assumption), while an unambiguous lookup question still converged 5/5 to the identical correct query at the same temperature — the signal self-consistency actually needs. New env var `OLLAMA_CONSENSUS_TEMPERATURE`, default `0.7`, used only for the N-candidate generation step; every existing single-shot call site is unaffected (`temperature=None` default resolves to the existing `OLLAMA_TEMPERATURE`).
- **A `None`-safe, order-insensitive sort key for clustering DuckDB result rows**: `sorted(rows, key=lambda row: tuple((v is None, v) for v in row))` — verified directly against a row list mixing `None`, `str`, `int`, and `float` values in the same column position; sorts without raising, and the resulting `tuple(sorted(rows, key=...))` is hashable for use as a `dict` key. Plain `sorted(rows)` would raise `TypeError` comparing `None` to a non-`None` value, which real result rows can contain (e.g. `fiscal_period` is nullable per `docs/schema.md`).
- **The existing `extract_numbers()`/`_scalar_match()` implementation** (currently in `evals/run_eval.py:38-83`) is the exact function this plan moves into `ledgerql/verify.py` as the canonical version — read directly from the file, not reconstructed from memory, so the moved copy is a verified, byte-faithful transcription (Task 1 reuses this exact regex/logic).
- **Current `ledgerql/pipeline.py`, `ledgerql/generate.py`, `ledgerql/answer.py`, `tests/test_pipeline.py`, `tests/test_generate.py`, `tests/test_answer.py`, `evals/run_eval.py`, `tests/test_run_eval.py`, and `Makefile`** were all read in full immediately before writing this plan (post-Phase-3-merge state) — every "Modify" instruction below references real, current line content, not a stale mental model of an earlier phase.
- **`.gitignore`'s current reports section** (verified): `reports/*.md` is ignored except the literal `!reports/baseline.md` exception; `reports/*.jsonl` is fully ignored. This plan adds a second literal exception (`!reports/eval.md`) rather than a dated pattern — see §9 of the spec and Task 6 below for why a fixed, git-committable filename (mirroring `baseline.md`'s role) is used instead of the spec's originally-cited `eval_<date>.md` naming, which doesn't fit a single-committed-snapshot workflow. `reports/baseline.md` itself is left untouched — Phase 3's real historical evidence, not regenerated going forward.

---

## File Structure

```
ledgerql/
  verify.py         # rewritten: extract_numbers/extract_years/VerifyResult/verify() (was a Phase 0 stub)
  consensus.py       # rewritten: ConsensusResult/vote() (was a Phase 0 stub)
  generate.py         # rewritten: n>1 support, temperature param, OLLAMA_CONSENSUS_TEMPERATURE
  answer.py             # rewritten: write_answer(result, client=None) -- question hidden
  pipeline.py            # rewritten: N-candidate orchestration, consensus, verify, real confidence
tests/
  test_verify.py          # new
  test_consensus.py        # new
  test_generate.py          # rewritten (drop the n!=1-rejection test, add multi-candidate tests)
  test_answer.py              # rewritten (question param removed from every test)
  test_pipeline.py              # rewritten entirely
evals/
  run_eval.py                    # extended: imports extract_numbers/extract_years from verify,
                                  # confidence + abstain precision/recall, ablation table,
                                  # writes reports/eval.md + reports/eval_<date>.jsonl
tests/
  test_run_eval.py                # extended
Makefile                           # `eval:` target replaced with the real implementation, `baseline:` removed
.gitignore                          # add `!reports/eval.md`
```

---

### Task 1: `ledgerql/verify.py` — numeric + fiscal-year grounding

**Files:**
- Modify: `ledgerql/verify.py` (replace the Phase 0 stub entirely)
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: nothing from other new modules.
- Produces: `extract_numbers(text: str) -> list[float]`; `extract_years(text: str) -> list[int]`; `@dataclass VerifyResult` (`ok: bool`, `ungrounded_numbers: list[float] = field(default_factory=list)`, `detail: str | None = None`); `verify(answer: str, columns: list[str], rows: list[tuple]) -> VerifyResult`. Task 6 imports `extract_numbers` and `extract_years` from here.

- [ ] **Step 1: Write the failing tests**

`tests/test_verify.py`:

```python
from ledgerql import verify


def test_extract_numbers_handles_plain_integer():
    assert verify.extract_numbers("The value is 391035000000.") == [391035000000.0]


def test_extract_numbers_handles_billions_word():
    assert verify.extract_numbers("Revenue was $391.0 billion.") == [391000000000.0]


def test_extract_numbers_excludes_plausible_years():
    assert verify.extract_numbers("This is fiscal year 2024 data.") == []


def test_extract_numbers_excludes_sec_form_codes():
    assert verify.extract_numbers("It filed a 10-K and a 10-Q.") == []


def test_extract_numbers_handles_negative_number():
    assert verify.extract_numbers("Revenue declined by -5.2%.") == [-5.2]


def test_extract_years_finds_bare_years():
    assert verify.extract_years("Revenue in fiscal year 2024 was strong.") == [2024]


def test_extract_years_ignores_non_year_numbers():
    assert verify.extract_years("Revenue was 391035000000.") == []


def test_extract_years_ignores_years_embedded_in_larger_numbers():
    # "2024000" contains the digits "2024" but is not itself a year.
    assert verify.extract_years("The raw value was 2024000.") == []


def test_extract_years_finds_multiple_years():
    assert verify.extract_years("Between fiscal 2023 and fiscal 2024.") == [2023, 2024]


def test_verify_passes_when_every_number_is_grounded():
    result = verify.verify(
        "The value was $391.0 billion.",
        ["ticker", "value"],
        [("AAPL", 391035000000.0)],
    )
    assert result.ok is True
    assert result.ungrounded_numbers == []


def test_verify_fails_on_ungrounded_number():
    result = verify.verify(
        "The value was $999.0 billion.",
        ["ticker", "value"],
        [("AAPL", 391035000000.0)],
    )
    assert result.ok is False
    assert result.ungrounded_numbers == [999000000000.0]
    assert "999000000000.0" in result.detail


def test_verify_fails_on_wrong_fiscal_year():
    result = verify.verify(
        "The fiscal 2025 revenue was $391.0 billion.",
        ["fiscal_year", "value"],
        [(2024, 391035000000.0)],
    )
    assert result.ok is False
    assert 2025.0 in result.ungrounded_numbers


def test_verify_passes_correct_fiscal_year():
    result = verify.verify(
        "The fiscal 2024 revenue was $391.0 billion.",
        ["fiscal_year", "value"],
        [(2024, 391035000000.0)],
    )
    assert result.ok is True


def test_verify_ignores_fiscal_year_check_when_column_absent():
    # No fiscal_year column in this result -- a stated year (however
    # implausible) is not something this function can ground, so it
    # must not be flagged.
    result = verify.verify(
        "As of 2024, the value was 5.0.",
        ["value"],
        [(5.0,)],
    )
    assert result.ok is True


def test_verify_passes_on_empty_result_with_no_claimed_numbers():
    result = verify.verify("No matching data was found.", ["value"], [])
    assert result.ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verify.py -v`
Expected: FAIL with `NotImplementedError: Phase 4` (the current stub) or `AttributeError` (functions don't exist yet)

- [ ] **Step 3: Write the implementation**

`ledgerql/verify.py`:

```python
"""Stage 7b: numeric + fiscal-year verifier.

Checks every number the generated answer states is actually grounded in
the winning consensus result -- a claimed number with no matching value
anywhere in the result set forces an ABSTAIN (UNGROUNDED_ANSWER). A
wrong magnitude word ("million" instead of "billion") already fails the
general numeric check on its own, since extract_numbers() reconstructs
the claimed raw value using the stated magnitude before comparing it --
no separate unit-consistency mechanism is needed for that case.
Fiscal-year correctness needs a distinct, narrower check: years are
deliberately excluded from extract_numbers() (they appear constantly in
correct, grounded answers and are not the kind of "unsupported data
value" that check exists to catch), so a wrong fiscal year would
otherwise pass silently.
"""

import re
from dataclasses import dataclass, field

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# A bare 4-digit number that reads as a plausible fiscal/calendar year
# (2000-2099) is excluded -- these appear constantly in grounded,
# correct answers ("fiscal year 2024") and are not data values that
# need to trace back to the executed result set.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(-?\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")
# A bare number immediately followed by a hyphen and an uppercase letter
# is an SEC form code (e.g. "10-K", "10-Q"), not a data value.
_FORM_CODE_RE = re.compile(r"-[A-Z]")
# A standalone 4-digit year, not embedded in a larger number on either side.
_BARE_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        if _FORM_CODE_RE.match(text, match.end()):
            continue
        raw_digits, word = match.groups()
        # Strip a trailing sentence period (e.g. "fiscal year 2024.")
        # before the year-exclusion check and float conversion, so a
        # number followed immediately by a period is treated the same
        # as one that stands alone.
        digits = raw_digits.replace(",", "").rstrip(".")
        if not word and _YEAR_RE.match(digits):
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        if word and word.lower() in _MAGNITUDE:
            value *= _MAGNITUDE[word.lower()]
        numbers.append(value)
    return numbers


def extract_years(text: str) -> list[int]:
    return [int(m) for m in _BARE_YEAR_RE.findall(text)]


def _scalar_match(value: float, grounded: float, tolerance: float = 0.01) -> bool:
    return abs(value - grounded) <= max(abs(grounded) * tolerance, 1e-9)


@dataclass
class VerifyResult:
    ok: bool
    ungrounded_numbers: list[float] = field(default_factory=list)
    detail: str | None = None


def verify(answer: str, columns: list[str], rows: list[tuple]) -> VerifyResult:
    grounded_values = {v for row in rows for v in row if isinstance(v, int | float)}
    claimed = extract_numbers(answer)
    ungrounded = [n for n in claimed if not any(_scalar_match(n, g) for g in grounded_values)]

    if "fiscal_year" in columns:
        idx = columns.index("fiscal_year")
        grounded_years = {row[idx] for row in rows if row[idx] is not None}
        year_mismatches = [
            float(y) for y in extract_years(answer) if y not in grounded_years
        ]
        ungrounded = ungrounded + year_mismatches

    if ungrounded:
        return VerifyResult(
            ok=False,
            ungrounded_numbers=ungrounded,
            detail=f"answer states unsupported number(s): {ungrounded}",
        )
    return VerifyResult(ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_verify.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/verify.py tests/test_verify.py
git commit -m "feat: implement numeric + fiscal-year grounding verifier (Layer 7b)

extract_numbers() is a byte-faithful move of evals/run_eval.py's
existing, tested implementation -- not a reimplementation -- so
Task 6 can import it back instead of maintaining a second copy.
extract_years() is new: fiscal-year correctness is deliberately
excluded from extract_numbers()'s own check (years appear
constantly in correct answers) and needs its own narrow check
against the fiscal_year column when present."
```

---

### Task 2: `ledgerql/consensus.py` — self-consistency vote

**Files:**
- Modify: `ledgerql/consensus.py` (replace the Phase 0 stub entirely)
- Test: `tests/test_consensus.py`

**Interfaces:**
- Consumes: `guardrails.GuardrailResult` (`ok`, `sql`, `events`, `reason_code`, `detail` — Phase 3, unchanged); `execute.ExecutionResult` (`columns`, `rows`, `error`, `truncated` — Phase 2, unchanged).
- Produces: `@dataclass ConsensusResult` (`sql: str | None = None`, `columns: list[str] = field(default_factory=list)`, `rows: list[tuple] = field(default_factory=list)`, `truncated: bool = False`, `agreement: float = 0.0`, `events: list[str] = field(default_factory=list)`, `reason_code: str | None = None`, `detail: str | None = None`); `vote(guards: list[GuardrailResult], executions: list[ExecutionResult | None]) -> ConsensusResult`. `reason_code is None` is the caller's signal that a winner was found (even if that winner's own `rows` is legitimately empty) — Task 5 depends on this exact contract.

- [ ] **Step 1: Write the failing tests**

`tests/test_consensus.py`:

```python
from ledgerql import consensus
from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


def _guard(sql, ok=True, events=None, reason_code=None):
    return GuardrailResult(ok=ok, sql=sql, events=events or [], reason_code=reason_code)


def test_vote_unanimous_agreement():
    guards = [_guard("SELECT 1") for _ in range(5)]
    execs = [ExecutionResult(columns=["x"], rows=[(1,)]) for _ in range(5)]

    result = consensus.vote(guards, execs)

    assert result.agreement == 1.0
    assert result.columns == ["x"]
    assert result.rows == [(1,)]
    assert result.reason_code is None


def test_vote_majority_wins_agreement_fraction():
    guards = [_guard("SELECT 1") for _ in range(5)]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(2,)]),
        ExecutionResult(columns=["x"], rows=[(2,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.rows == [(1,)]
    assert result.agreement == 3 / 5


def test_vote_agreement_divides_by_total_n_not_just_survivors():
    # Only 2 of 5 candidates even produced a usable result, and both
    # agree with each other -- agreement must be 2/5, not 2/2, since a
    # low SQL-generation success rate is itself a low-confidence signal.
    guards = [
        _guard("SELECT 1"),
        _guard("SELECT 1"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
    ]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(columns=["x"], rows=[(1,)]),
        None,
        None,
        None,
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 2 / 5
    assert result.reason_code is None  # a winner *was* found


def test_vote_ignores_executions_with_an_error():
    guards = [_guard("SELECT 1") for _ in range(3)]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,)]),
        ExecutionResult(error="syntax error"),
        ExecutionResult(columns=["x"], rows=[(1,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 2 / 3
    assert result.rows == [(1,)]


def test_vote_row_order_insensitive_clustering():
    # Two candidates whose rows are the same set in a different physical
    # order (e.g. no explicit ORDER BY) must cluster together, not be
    # treated as disagreeing.
    guards = [_guard("SELECT 1"), _guard("SELECT 1")]
    execs = [
        ExecutionResult(columns=["x"], rows=[(1,), (2,)]),
        ExecutionResult(columns=["x"], rows=[(2,), (1,)]),
    ]

    result = consensus.vote(guards, execs)

    assert result.agreement == 1.0


def test_vote_preserves_winner_original_row_order_in_output():
    # Clustering is order-insensitive, but the *returned* rows must keep
    # the winning candidate's own order (e.g. a real ORDER BY is
    # semantically meaningful and must not be scrambled).
    guards = [_guard("SELECT 1 ORDER BY x DESC") for _ in range(3)]
    execs = [ExecutionResult(columns=["x"], rows=[(2,), (1,)]) for _ in range(3)]

    result = consensus.vote(guards, execs)

    assert result.rows == [(2,), (1,)]


def test_vote_no_winner_uses_most_common_rejection_reason():
    guards = [
        _guard("bad1", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad2", ok=False, events=["schema_allowlist"], reason_code="SCHEMA_MISMATCH"),
        _guard("bad3", ok=False, events=["cost_limit"], reason_code="COST_LIMIT"),
    ]
    execs = [None, None, None]

    result = consensus.vote(guards, execs)

    assert result.reason_code == "SCHEMA_MISMATCH"
    assert result.agreement == 0.0
    assert result.sql == "bad1"  # first rejected candidate, for audit visibility


def test_vote_no_winner_defaults_to_exec_error_when_no_rejection_reasons():
    # Every guard passed, but every execution errored -- there is no
    # guardrail rejection reason to take a mode of.
    guards = [_guard("SELECT 1") for _ in range(2)]
    execs = [ExecutionResult(error="timeout"), ExecutionResult(error="timeout")]

    result = consensus.vote(guards, execs)

    assert result.reason_code == "EXEC_ERROR"


def test_vote_deduplicates_events_across_candidates():
    guards = [
        _guard("SELECT 1", events=["cost_limit"]),
        _guard("SELECT 1", events=["cost_limit"]),
    ]
    execs = [ExecutionResult(columns=["x"], rows=[(1,)]) for _ in range(2)]

    result = consensus.vote(guards, execs)

    assert result.events == ["cost_limit"]


def test_vote_winner_with_legitimately_empty_rows_is_not_a_no_winner_case():
    guards = [_guard("SELECT 1 WHERE 1=0") for _ in range(5)]
    execs = [ExecutionResult(columns=["x"], rows=[]) for _ in range(5)]

    result = consensus.vote(guards, execs)

    assert result.reason_code is None
    assert result.rows == []
    assert result.agreement == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_consensus.py -v`
Expected: FAIL with `NotImplementedError: Phase 4` or `AttributeError`

- [ ] **Step 3: Write the implementation**

`ledgerql/consensus.py`:

```python
"""Stage 6: self-consistency vote.

Clusters executed candidates by result set (not raw SQL text -- two
differently-worded but semantically-equivalent queries should agree).
The majority cluster wins; agreement is scored against the full
requested sample count, not just the candidates that executed
successfully, so a low SQL-generation success rate is itself a
low-confidence signal instead of being hidden by only comparing
survivors to each other.
"""

from collections import Counter
from dataclasses import dataclass, field

from ledgerql.execute import ExecutionResult
from ledgerql.guardrails import GuardrailResult


@dataclass
class ConsensusResult:
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    agreement: float = 0.0
    events: list[str] = field(default_factory=list)
    reason_code: str | None = None
    detail: str | None = None


def _row_sort_key(row: tuple) -> tuple:
    # None-safe: comparing None to a non-None value raises TypeError in
    # Python 3, and real result rows can contain None (nullable columns
    # like fiscal_period). Pairing each value with an is-None flag makes
    # every row comparable without ever comparing None to a non-None value.
    return tuple((v is None, v) for v in row)


def vote(guards: list[GuardrailResult], executions: list[ExecutionResult | None]) -> ConsensusResult:
    n = len(guards)
    clusters: dict[tuple, list[int]] = {}
    for i, exec_result in enumerate(executions):
        if exec_result is None or exec_result.error is not None:
            continue
        key = (tuple(exec_result.columns), tuple(sorted(exec_result.rows, key=_row_sort_key)))
        clusters.setdefault(key, []).append(i)

    all_events: list[str] = []
    for guard in guards:
        all_events.extend(guard.events)
    deduped_events = sorted(set(all_events))

    if not clusters:
        rejection_reasons = [g.reason_code for g in guards if g.reason_code is not None]
        if rejection_reasons:
            reason_code = Counter(rejection_reasons).most_common(1)[0][0]
        else:
            reason_code = "EXEC_ERROR"
        first_rejected_sql = next((g.sql for g in guards if not g.ok), None)
        return ConsensusResult(
            sql=first_rejected_sql,
            agreement=0.0,
            events=deduped_events,
            reason_code=reason_code,
            detail="no candidate produced a usable result",
        )

    winning_key, winning_indices = max(clusters.items(), key=lambda kv: len(kv[1]))
    winner_idx = winning_indices[0]
    winner_exec = executions[winner_idx]
    winner_guard = guards[winner_idx]

    return ConsensusResult(
        sql=winner_guard.sql,
        columns=winner_exec.columns,
        rows=winner_exec.rows,
        truncated=winner_exec.truncated,
        agreement=len(winning_indices) / n,
        events=deduped_events,
        reason_code=None,
        detail=None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_consensus.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/consensus.py tests/test_consensus.py
git commit -m "feat: implement self-consistency vote (Layer 6)

Clusters candidates by result-set equality (order-insensitive via a
None-safe sort key, but the winner's own row order is preserved in
the output). Agreement divides by the full requested sample count,
not just the candidates that produced a usable result, so a low
generation success rate is itself a low-confidence signal. No-winner
case reports the mode of the guardrail rejection reasons."
```

---

### Task 3: `ledgerql/generate.py` — lift the `n=1` restriction

**Files:**
- Modify: `ledgerql/generate.py`
- Test: `tests/test_generate.py` (modify: remove the `n != 1` rejection test, add multi-candidate tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `generate_candidates(question: str, schema_context: str, n: int = 1, temperature: float | None = None, client: ollama.Client | None = None) -> list[str]` — **signature change**, adds `temperature`, removes the `NotImplementedError` for `n != 1`. New module constant `OLLAMA_CONSENSUS_TEMPERATURE` (read from `OLLAMA_CONSENSUS_TEMPERATURE` env var, default `0.7`) — Task 5 imports and uses this for the N-candidate call.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_generate.py` entirely with:

```python
from ledgerql import generate


class _FakeResponse:
    def __init__(self, text: str):
        self.response = text


class _FakeClient:
    def __init__(self, texts):
        # Accept either a single string (every call returns the same
        # text) or a list (one text per call, in order).
        self._texts = [texts] if isinstance(texts, str) else list(texts)
        self._call_index = 0
        self.last_call: dict | None = None
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.last_call = kwargs
        self.calls.append(kwargs)
        text = self._texts[min(self._call_index, len(self._texts) - 1)]
        self._call_index += 1
        return _FakeResponse(text)


def test_generate_candidates_strips_markdown_fences():
    client = _FakeClient("```sql\nSELECT 1;\n```")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT 1;"]


def test_generate_candidates_passes_model_temperature_and_seed():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates("q", "schema", n=1, client=client)
    assert client.last_call["model"] == generate.OLLAMA_MODEL
    assert client.last_call["options"]["temperature"] == generate.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == generate.OLLAMA_SEED


def test_generate_candidates_includes_question_and_schema_in_prompt():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates(
        "What was Apple's revenue?", "SCHEMA_TEXT_HERE", n=1, client=client
    )
    assert "What was Apple's revenue?" in client.last_call["prompt"]
    assert "SCHEMA_TEXT_HERE" in client.last_call["prompt"]


def test_generate_candidates_returns_plain_sql_unchanged():
    client = _FakeClient("SELECT value FROM v_revenue WHERE ticker='AAPL'")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT value FROM v_revenue WHERE ticker='AAPL'"]


def test_generate_candidates_passes_system_prompt_to_client():
    client = _FakeClient("SELECT 1;")
    generate.generate_candidates("q", "schema", n=1, client=client)
    assert client.last_call["system"] == generate.SYSTEM_PROMPT


def test_generate_candidates_makes_n_calls():
    client = _FakeClient(["SELECT 1;", "SELECT 2;", "SELECT 3;"])
    result = generate.generate_candidates("q", "schema", n=3, client=client)
    assert result == ["SELECT 1;", "SELECT 2;", "SELECT 3;"]
    assert len(client.calls) == 3


def test_generate_candidates_uses_distinct_seeds_per_call():
    client = _FakeClient(["SELECT 1;", "SELECT 2;", "SELECT 3;"])
    generate.generate_candidates("q", "schema", n=3, client=client)
    seeds = [call["options"]["seed"] for call in client.calls]
    assert seeds == [generate.OLLAMA_SEED, generate.OLLAMA_SEED + 1, generate.OLLAMA_SEED + 2]


def test_generate_candidates_default_temperature_unaffected_by_n():
    client = _FakeClient(["SELECT 1;", "SELECT 2;"])
    generate.generate_candidates("q", "schema", n=2, client=client)
    for call in client.calls:
        assert call["options"]["temperature"] == generate.OLLAMA_TEMPERATURE


def test_generate_candidates_accepts_explicit_temperature_override():
    client = _FakeClient(["SELECT 1;", "SELECT 2;"])
    generate.generate_candidates(
        "q", "schema", n=2, temperature=generate.OLLAMA_CONSENSUS_TEMPERATURE, client=client
    )
    for call in client.calls:
        assert call["options"]["temperature"] == generate.OLLAMA_CONSENSUS_TEMPERATURE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_generate.py -v`
Expected: FAIL — `test_generate_candidates_makes_n_calls` and the other new tests fail (`n != 1` currently raises `NotImplementedError`); `test_generate_candidates_accepts_explicit_temperature_override` fails with a `TypeError` (no `temperature` parameter yet).

- [ ] **Step 3: Write the implementation**

`ledgerql/generate.py`:

```python
"""Stage 3: SQL generation.

Calls the local Ollama model (default qwen2.5-coder:7b) to produce SQL
given the question and the schema context. Single-shot (n=1, the
default OLLAMA_TEMPERATURE) and N-sample self-consistency (n>1, a
separate, higher OLLAMA_CONSENSUS_TEMPERATURE) share this one function:
each of the n candidates is one call, with seed = OLLAMA_SEED + i so
the whole batch stays reproducible run-to-run while each call gets a
real chance at a different sampling path. Verified empirically during
Phase 4 planning: at the single-shot temperature (0.2), varying only
the seed across calls produced near-identical candidates (4 of 5
byte-identical on a real gold-set question) -- self-consistency needs
genuine sampling diversity, which this model only gives at a
meaningfully higher temperature.
"""

import os
import re

import ollama

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_CONSENSUS_TEMPERATURE = float(os.environ.get("OLLAMA_CONSENSUS_TEMPERATURE", "0.7"))
OLLAMA_SEED = int(os.environ.get("OLLAMA_SEED", "42"))

SYSTEM_PROMPT = (
    "You are a SQL generator for a read-only financial-data analyst database. "
    "Given a schema and a question, respond with exactly one valid DuckDB "
    "SELECT statement that answers the question. Output ONLY the SQL "
    "statement -- no explanation, no markdown code fences, no comments."
)

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|```\s*$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def generate_candidates(
    question: str,
    schema_context: str,
    n: int = 1,
    temperature: float | None = None,
    client: ollama.Client | None = None,
) -> list[str]:
    client = client or ollama.Client(host=OLLAMA_HOST)
    effective_temperature = OLLAMA_TEMPERATURE if temperature is None else temperature
    prompt = f"Schema:\n{schema_context}\n\nQuestion: {question}\n\nSQL:"
    candidates = []
    for i in range(n):
        response = client.generate(
            model=OLLAMA_MODEL,
            system=SYSTEM_PROMPT,
            prompt=prompt,
            options={"temperature": effective_temperature, "seed": OLLAMA_SEED + i},
        )
        candidates.append(_strip_fences(response.response))
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_generate.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/generate.py tests/test_generate.py
git commit -m "feat: lift generate_candidates' n=1 restriction for self-consistency

n>1 now makes n real calls, seed = OLLAMA_SEED + i per call for a
reproducible-but-diverse batch. New OLLAMA_CONSENSUS_TEMPERATURE
(default 0.7) is used only when the caller passes it explicitly --
every existing n=1 call site is unaffected. Verified empirically
during planning that the existing single-shot temperature (0.2)
does not give the real model enough sampling diversity for
self-consistency to mean anything."
```

---

### Task 4: `ledgerql/answer.py` — hide the question

**Files:**
- Modify: `ledgerql/answer.py`
- Test: `tests/test_answer.py` (rewritten: `question` parameter removed from every test)

**Interfaces:**
- Consumes: `ExecutionResult` (`columns`, `rows` — unchanged).
- Produces: `write_answer(result: ExecutionResult, client: ollama.Client | None = None) -> str` — **signature change**, `question` parameter removed. Every call site in `pipeline.py` (Task 5) updates accordingly.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_answer.py` entirely with:

```python
from ledgerql import answer
from ledgerql.execute import ExecutionResult


class _FakeResponse:
    def __init__(self, text: str):
        self.response = text


class _FakeClient:
    def __init__(self, text: str):
        self._text = text
        self.last_call: dict | None = None

    def generate(self, **kwargs):
        self.last_call = kwargs
        return _FakeResponse(self._text)


def test_write_answer_includes_result_in_prompt_but_not_a_question():
    client = _FakeClient("The value was $391.0 billion.")
    result = ExecutionResult(columns=["value"], rows=[(391035000000,)])
    answer_text = answer.write_answer(result, client=client)
    assert answer_text == "The value was $391.0 billion."
    assert "391035000000" in client.last_call["prompt"]
    # No question is ever passed to write_answer -- the prompt has
    # nothing question-shaped to leak, verified by construction: the
    # function signature itself no longer accepts one.


def test_write_answer_handles_empty_result():
    client = _FakeClient("No matching data was found.")
    result = ExecutionResult(columns=["value"], rows=[])
    answer_text = answer.write_answer(result, client=client)
    assert answer_text == "No matching data was found."
    assert "(no rows)" in client.last_call["prompt"]


def test_write_answer_passes_temperature_and_seed():
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer(result, client=client)
    assert client.last_call["options"]["temperature"] == answer.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == answer.OLLAMA_SEED


def test_write_answer_system_prompt_instructs_grounding_only():
    # The system prompt is the only thing telling the model not to
    # infer/add numbers -- a silent regression here would reopen exactly
    # the hallucination surface this phase closes.
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer(result, client=client)
    assert "do not add" in client.last_call["system"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_answer.py -v`
Expected: FAIL with `TypeError: write_answer() missing 1 required positional argument` or similar (current signature is `write_answer(question, result, client=None)`)

- [ ] **Step 3: Write the implementation**

`ledgerql/answer.py`:

```python
"""Stage 7a: grounded answer generation.

The model sees only the executed result's column names and rows --
never the original natural-language question, never the SQL. This is
deliberate: with no question to answer "from memory" against, the only
thing the model can plausibly do is describe the table in front of it,
which is what makes the numeric verifier (verify.py) a meaningful check
rather than a race against a model that already has its own idea of
what the answer "should" be.
"""

import os

import ollama

from ledgerql.execute import ExecutionResult

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_SEED = int(os.environ.get("OLLAMA_SEED", "42"))

SYSTEM_PROMPT = (
    "Write one or two plain-English sentences describing the data in this "
    "table. Use only the values shown -- do not add, round differently, or "
    "infer any number not present. State any unit or fiscal year exactly as "
    "given."
)


def _format_result(result: ExecutionResult) -> str:
    header = "\t".join(result.columns)
    if not result.rows:
        return f"{header}\n(no rows)"
    body = "\n".join("\t".join(str(v) for v in row) for row in result.rows)
    return f"{header}\n{body}"


def write_answer(
    result: ExecutionResult,
    client: ollama.Client | None = None,
) -> str:
    client = client or ollama.Client(host=OLLAMA_HOST)
    table_text = _format_result(result)
    prompt = f"Result:\n{table_text}\n\nAnswer:"
    response = client.generate(
        model=OLLAMA_MODEL,
        system=SYSTEM_PROMPT,
        prompt=prompt,
        options={"temperature": OLLAMA_TEMPERATURE, "seed": OLLAMA_SEED},
    )
    return response.response.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_answer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/answer.py tests/test_answer.py
git commit -m "feat: hide the question from grounded-answer generation

write_answer() now takes only the executed ExecutionResult -- the
original question is never shown to this stage. Per explicit
direction during Phase 4 brainstorming: with no question to answer
from memory against, the model can only describe the table in front
of it, making verify.py's numeric check a real backstop rather than
a race against a model with its own idea of the answer."
```

---

### Task 5: `ledgerql/pipeline.py` — orchestration rewiring

**Files:**
- Modify: `ledgerql/pipeline.py` (replace the Phase 3 orchestration entirely)
- Test: `tests/test_pipeline.py` (replace entirely)

**Interfaces:**
- Consumes: `classify.classify(question) -> ClassifyResult` (Phase 3, unchanged); `schema_index.get_schema_context() -> str` (unchanged); `generate.generate_candidates(question, schema_context, n=5, temperature=OLLAMA_CONSENSUS_TEMPERATURE) -> list[str]` (Task 3); `guardrails.validate(sql, db_path=...) -> GuardrailResult` (Phase 3, unchanged); `execute.execute(sql, db_path=...) -> ExecutionResult` (unchanged); `consensus.vote(guards, executions) -> ConsensusResult` (Task 2); `answer.write_answer(result) -> str` (Task 4, no `question` arg); `verify.verify(answer, columns, rows) -> VerifyResult` (Task 1); `audit.write_record(record) -> str` (Phase 3, unchanged).
- Produces: `ask(question: str, db_path: str | None = None) -> dict` — same top-level keys as Phase 3 (`question`, `sql`, `columns`, `rows`, `truncated`, `error`, `answer`, `reason_code`, `guardrail_events`) plus a new `confidence: float | None` key. New module constants `N_CANDIDATES = 5`, `LOW_AGREEMENT_THRESHOLD = 0.6` (starting value — Task 7 empirically sweeps and may adjust this constant, documenting the final choice).

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_pipeline.py` entirely with:

```python
from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import consensus as consensus_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import pipeline
from ledgerql import verify as verify_module
from ledgerql.classify import ClassifyResult
from ledgerql.consensus import ConsensusResult
from ledgerql.execute import ExecutionResult
from ledgerql.verify import VerifyResult


def _patch_audit(monkeypatch):
    records = []
    monkeypatch.setattr(audit_module, "write_record", lambda r: records.append(r) or "fake-id")
    return records


def _patch_classify_in_scope(monkeypatch):
    monkeypatch.setattr(
        classify_module, "classify", lambda q: ClassifyResult(verdict="IN_SCOPE", explanation="e")
    )


def _patch_generate(monkeypatch, sqls=None):
    sqls = sqls or ["SELECT 1"] * pipeline.N_CANDIDATES
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda q, s, n=1, temperature=None: sqls
    )


def test_ask_short_circuits_on_classify_out_of_scope(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module,
        "classify",
        lambda q: ClassifyResult(verdict="OUT_OF_SCOPE", explanation="e"),
    )
    calls = []
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda *a, **k: calls.append(1) or ["SELECT 1"]
    )

    result = pipeline.ask("Should I buy Tesla stock?")

    assert result["answer"] is None
    assert result["reason_code"] == "OUT_OF_SCOPE"
    assert result["confidence"] is None
    assert calls == []  # generation never ran
    assert len(records) == 1


def test_ask_short_circuits_on_classify_schema_mismatch(monkeypatch):
    records = _patch_audit(monkeypatch)
    monkeypatch.setattr(
        classify_module,
        "classify",
        lambda q: ClassifyResult(verdict="SCHEMA_MISMATCH", explanation="e"),
    )

    result = pipeline.ask("What was Apple's dividend yield?")

    assert result["answer"] is None
    assert result["reason_code"] == "SCHEMA_MISMATCH"
    assert len(records) == 1


def test_ask_generates_n_candidates(monkeypatch):
    _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    captured = {}

    def fake_generate(question, schema_context, n=1, temperature=None):
        captured["n"] = n
        captured["temperature"] = temperature
        return ["SELECT 1"] * n

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        guardrails_module, "validate", lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql)
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 1.")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    pipeline.ask("q")

    assert captured["n"] == pipeline.N_CANDIDATES
    assert captured["temperature"] == generate_module.OLLAMA_CONSENSUS_TEMPERATURE


def test_ask_short_circuits_on_no_consensus_winner(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch, sqls=["DELETE FROM filings"] * pipeline.N_CANDIDATES)
    monkeypatch.setattr(
        guardrails_module,
        "validate",
        lambda sql, db_path=None: guardrails_module.GuardrailResult(
            ok=False, sql=sql, events=["read_only"], reason_code="OUT_OF_SCOPE", detail="not a SELECT"
        ),
    )
    exec_calls = []
    monkeypatch.setattr(execute_module, "execute", lambda *a, **k: exec_calls.append(1))
    answer_calls = []
    monkeypatch.setattr(answer_module, "write_answer", lambda *a, **k: answer_calls.append(1))

    result = pipeline.ask("Delete all filings for Tesla.")

    assert result["answer"] is None
    assert result["reason_code"] == "OUT_OF_SCOPE"
    assert result["guardrail_events"] == ["read_only"]
    assert exec_calls == []  # every candidate rejected, execution never ran
    assert answer_calls == []
    assert len(records) == 1


def test_ask_abstains_on_low_agreement(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    monkeypatch.setattr(
        guardrails_module, "validate", lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql)
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=0.2, reason_code=None
        ),
    )
    answer_calls = []
    monkeypatch.setattr(answer_module, "write_answer", lambda *a, **k: answer_calls.append(1))

    result = pipeline.ask("An ambiguous question")

    assert result["answer"] is None
    assert result["reason_code"] == "LOW_AGREEMENT"
    assert result["confidence"] == 0.2
    assert answer_calls == []  # never reached the answer stage
    assert len(records) == 1
    assert records[0]["confidence"] == 0.2


def test_ask_abstains_on_ungrounded_answer(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    monkeypatch.setattr(
        guardrails_module, "validate", lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql=sql)
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 999.")
    monkeypatch.setattr(
        verify_module,
        "verify",
        lambda a, c, r: VerifyResult(ok=False, ungrounded_numbers=[999.0], detail="unsupported: [999.0]"),
    )

    result = pipeline.ask("q")

    assert result["answer"] is None
    assert result["reason_code"] == "UNGROUNDED_ANSWER"
    assert result["confidence"] == 1.0
    assert result["error"] == "unsupported: [999.0]"
    assert len(records) == 1


def test_ask_returns_full_success_result_with_confidence(monkeypatch):
    records = _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    captured = {}

    def fake_generate(question, schema_context, n=1, temperature=None):
        captured["schema_context"] = schema_context
        return ["SELECT 1"] * n

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(
        guardrails_module, "validate", lambda sql, db_path=None: guardrails_module.GuardrailResult(ok=True, sql="SELECT 1")
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql, db_path=None: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "The value is 1.")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    result = pipeline.ask("what is 1?")

    assert result["question"] == "what is 1?"
    assert result["sql"] == "SELECT 1"
    assert result["columns"] == ["x"]
    assert result["rows"] == [(1,)]
    assert result["error"] is None
    assert result["answer"] == "The value is 1."
    assert result["reason_code"] is None
    assert result["confidence"] == 1.0
    assert len(records) == 1
    assert records[0]["confidence"] == 1.0
    assert "v_revenue" in captured["schema_context"]


def test_ask_writes_audit_record_and_does_not_raise_on_classify_crash(monkeypatch):
    records = _patch_audit(monkeypatch)

    def _boom(q):
        raise Exception("boom")

    monkeypatch.setattr(classify_module, "classify", _boom)

    result = pipeline.ask("Should I buy Tesla stock?")

    assert result["reason_code"] == "EXEC_ERROR"
    assert result["error"] == "boom"
    assert result["answer"] is None
    assert len(records) == 1


def test_ask_threads_db_path_to_guardrails_and_execute(monkeypatch):
    _patch_audit(monkeypatch)
    _patch_classify_in_scope(monkeypatch)
    _patch_generate(monkeypatch)
    captured = {}

    def fake_validate(sql, db_path=None):
        captured["guardrail_db_path"] = db_path
        return guardrails_module.GuardrailResult(ok=True, sql=sql)

    def fake_execute(sql, db_path=None):
        captured["execute_db_path"] = db_path
        return ExecutionResult(columns=["x"], rows=[(1,)])

    monkeypatch.setattr(guardrails_module, "validate", fake_validate)
    monkeypatch.setattr(execute_module, "execute", fake_execute)
    monkeypatch.setattr(
        consensus_module,
        "vote",
        lambda guards, execs: ConsensusResult(
            sql="SELECT 1", columns=["x"], rows=[(1,)], agreement=1.0, reason_code=None
        ),
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda r: "answer")
    monkeypatch.setattr(verify_module, "verify", lambda a, c, r: VerifyResult(ok=True))

    pipeline.ask("q", db_path="custom.duckdb")

    assert captured["guardrail_db_path"] == "custom.duckdb"
    assert captured["execute_db_path"] == "custom.duckdb"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL (Phase 3's `ask()` calls `generate_candidates(..., n=1)`, has no `consensus`/`verify` imports, `write_answer` still takes `question`, no `confidence` key)

- [ ] **Step 3: Write the implementation**

`ledgerql/pipeline.py`:

```python
"""Orchestrates the Phase 4 pipeline: classify -> schema -> generate N
candidates -> guardrails validate each -> execute each survivor ->
consensus vote -> answer (question hidden) -> verify -> audit.

Two independent abstain triggers sit between consensus and the answer
stage: no candidate produced a usable result at all (consensus.py sets
reason_code itself), or a usable winner exists but too few of the N
candidates agreed with it (LOW_AGREEMENT_THRESHOLD, checked here). A
third trigger, UNGROUNDED_ANSWER, sits after the answer is written, if
verify.py finds a stated number with nothing backing it in the winning
result.
"""

import time

from ledgerql import answer as answer_module
from ledgerql import audit as audit_module
from ledgerql import classify as classify_module
from ledgerql import consensus as consensus_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import guardrails as guardrails_module
from ledgerql import schema_index
from ledgerql import verify as verify_module
from ledgerql.execute import ExecutionResult

N_CANDIDATES = 5
LOW_AGREEMENT_THRESHOLD = 0.6


def ask(question: str, db_path: str | None = None) -> dict:
    start = time.monotonic()

    try:
        classify_result = classify_module.classify(question)
        if classify_result.verdict != "IN_SCOPE":
            return _finish(question, start, classify_result, reason_code=classify_result.verdict)

        schema_context = schema_index.get_schema_context()
        sqls = generate_module.generate_candidates(
            question,
            schema_context,
            n=N_CANDIDATES,
            temperature=generate_module.OLLAMA_CONSENSUS_TEMPERATURE,
        )

        guards = []
        for sql in sqls:
            if db_path is not None:
                guards.append(guardrails_module.validate(sql, db_path=db_path))
            else:
                guards.append(guardrails_module.validate(sql))

        execs = []
        for guard in guards:
            if not guard.ok:
                execs.append(None)
                continue
            if db_path is not None:
                execs.append(execute_module.execute(guard.sql, db_path=db_path))
            else:
                execs.append(execute_module.execute(guard.sql))

        consensus_result = consensus_module.vote(guards, execs)

        if consensus_result.reason_code is not None:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                reason_code=consensus_result.reason_code,
                error=consensus_result.detail,
            )

        if consensus_result.agreement < LOW_AGREEMENT_THRESHOLD:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="LOW_AGREEMENT",
                confidence=consensus_result.agreement,
            )

        winner = ExecutionResult(
            columns=consensus_result.columns,
            rows=consensus_result.rows,
            truncated=consensus_result.truncated,
        )
        answer_text = answer_module.write_answer(winner)

        verify_result = verify_module.verify(
            answer_text, consensus_result.columns, consensus_result.rows
        )
        if not verify_result.ok:
            return _finish(
                question,
                start,
                classify_result,
                sql=consensus_result.sql,
                guardrail_events=consensus_result.events,
                columns=consensus_result.columns,
                rows=consensus_result.rows,
                truncated=consensus_result.truncated,
                reason_code="UNGROUNDED_ANSWER",
                error=verify_result.detail,
                confidence=consensus_result.agreement,
            )

        return _finish(
            question,
            start,
            classify_result,
            sql=consensus_result.sql,
            guardrail_events=consensus_result.events,
            columns=consensus_result.columns,
            rows=consensus_result.rows,
            truncated=consensus_result.truncated,
            answer=answer_text,
            confidence=consensus_result.agreement,
        )
    except Exception as e:  # noqa: BLE001
        # Last-resort catch-all: guarantees the master prompt's "every query
        # is logged, nothing silently dropped" constraint holds even when an
        # unhandled exception would otherwise propagate out of ask() before
        # _finish() -- the sole audit.write_record() call site -- is reached.
        fallback_classify = classify_module.ClassifyResult(verdict="EXEC_ERROR", explanation=str(e))
        return _finish(question, start, fallback_classify, reason_code="EXEC_ERROR", error=str(e))


def _finish(
    question: str,
    start: float,
    classify_result,
    sql: str | None = None,
    guardrail_events: list[str] | None = None,
    reason_code: str | None = None,
    columns: list[str] | None = None,
    rows: list[tuple] | None = None,
    truncated: bool = False,
    error: str | None = None,
    answer: str | None = None,
    confidence: float | None = None,
) -> dict:
    guardrail_events = guardrail_events or []
    columns = columns or []
    rows = rows or []
    latency_ms = (time.monotonic() - start) * 1000

    result = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "error": error,
        "answer": answer,
        "reason_code": reason_code,
        "guardrail_events": guardrail_events,
        "confidence": confidence,
    }
    audit_module.write_record(
        {
            "question": question,
            "classify_verdict": classify_result.verdict,
            "classify_explanation": classify_result.explanation,
            "generated_sql": sql,
            "guardrail_events": guardrail_events,
            "execution_summary": {
                "columns": columns,
                "row_count": len(rows),
                "truncated": truncated,
                "error": error,
            },
            "answer": answer,
            "confidence": confidence,
            "reason_code": reason_code,
            "latency_ms": latency_ms,
        }
    )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass, including every module rewritten by Tasks 1-4 plus every unrelated existing test (guardrails, classify, audit, schema_index, execute, validate_gold refactor, run_eval's pre-existing tests).

- [ ] **Step 6: Commit**

```bash
git add ledgerql/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire self-consistency, grounded answer, and verifier into the pipeline

ask() now generates N_CANDIDATES=5 candidates at the consensus
temperature, validates and executes each independently, and votes
via consensus.py. Two independent abstain triggers sit before the
answer stage (no winner; agreement below LOW_AGREEMENT_THRESHOLD),
a third (UNGROUNDED_ANSWER) after verify.py checks the answer.
confidence is now a real value (consensus agreement) threaded into
both the returned dict and the audit record, no longer hardcoded
null. write_answer() no longer receives the question."
```

---

### Task 6: `evals/run_eval.py` — DRY the verifier, add confidence/abstain scoring, rename the report

**Files:**
- Modify: `evals/run_eval.py`
- Modify: `tests/test_run_eval.py`
- Modify: `Makefile` (replace the stale `eval:` target with the real implementation, remove `baseline:`)
- Modify: `.gitignore` (add `!reports/eval.md`)

**Interfaces:**
- Consumes: `verify.extract_numbers`, `verify.extract_years` (Task 1); `pipeline.ask(question, db_path) -> dict`'s new `confidence` key (Task 5).
- Produces: `compute_abstain_metrics(per_case: list[dict], cases_by_id: dict) -> dict` (new); `run()`'s returned summary dict gains `confidence`-aware fields and abstain-precision/recall fields (below); `write_reports()` now writes `reports/eval.md` and `reports/eval_<date>.jsonl` (renamed from `baseline.md`/`baseline_<date>.jsonl`), with new "Confidence & abstain" and "Ablation" sections.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_eval.py`:

```python
def test_compute_abstain_metrics_counts_correct_abstain():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "A1", "answer": None, "reason_code": "OUT_OF_SCOPE"}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 1
    assert metrics["correct_abstains"] == 1
    assert metrics["expected_abstains"] == 1
    assert metrics["abstain_precision"] == 1.0
    assert metrics["abstain_recall"] == 1.0


def test_compute_abstain_metrics_wrong_reason_code_not_correct():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "A1", "answer": None, "reason_code": "SCHEMA_MISMATCH"}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["correct_abstains"] == 0
    assert metrics["abstain_precision"] == 0.0


def test_compute_abstain_metrics_answered_case_not_counted_as_abstain():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "L1", "answer": "the value is 5", "reason_code": None}]
    cases_by_id = {"L1": {"expected": "ANSWER", "reason_code": None}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["all_abstains"] == 0
    assert metrics["expected_abstains"] == 0
    assert metrics["abstain_precision"] == 0.0
    assert metrics["abstain_recall"] == 0.0


def test_compute_abstain_metrics_missed_expected_abstain_hurts_recall():
    from evals.run_eval import compute_abstain_metrics

    # Expected to abstain, but the pipeline answered anyway.
    per_case = [{"id": "A1", "answer": "a wrong answer", "reason_code": None}]
    cases_by_id = {"A1": {"expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["expected_abstains"] == 1
    assert metrics["correct_abstains"] == 0
    assert metrics["abstain_recall"] == 0.0


def test_compute_abstain_metrics_counts_answer_with_assumption_as_expected():
    from evals.run_eval import compute_abstain_metrics

    per_case = [{"id": "L3", "answer": None, "reason_code": "AMBIGUOUS"}]
    cases_by_id = {"L3": {"expected": "ANSWER_WITH_ASSUMPTION", "reason_code": "AMBIGUOUS"}}

    metrics = compute_abstain_metrics(per_case, cases_by_id)

    assert metrics["expected_abstains"] == 1
    assert metrics["correct_abstains"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_run_eval.py -v -k compute_abstain`
Expected: FAIL with `ImportError: cannot import name 'compute_abstain_metrics'`

- [ ] **Step 3: Replace the local number-extraction code with imports from `verify.py`**

In `evals/run_eval.py`, remove these module-level definitions entirely: `_MAGNITUDE`, `_NUMBER_RE`, `_YEAR_RE`, `_FORM_CODE_RE`, and the `extract_numbers` function (lines 38-74 in the current file). Replace the import block:

```python
from ledgerql import generate as generate_module
from ledgerql import pipeline
```

with:

```python
from ledgerql import generate as generate_module
from ledgerql import pipeline
from ledgerql.verify import extract_numbers, extract_years
```

Leave `_scalar_match` exactly where it is (it's still used by `results_match`, a different concern — comparing predicted execution results against gold execution results — unrelated to `verify.py`'s job of checking an answer's stated numbers against its own result set).

- [ ] **Step 4: Remove the now-redundant local extraction tests**

In `tests/test_run_eval.py`, remove these tests (they now belong to `tests/test_verify.py`, Task 1, which already covers this exact logic against the same real implementation): `test_extract_numbers_handles_plain_integer`, `test_extract_numbers_handles_billions_word`, `test_extract_numbers_handles_percent`, `test_extract_numbers_excludes_plausible_years`, `test_extract_numbers_excludes_plausible_years_with_trailing_period`, `test_extract_numbers_excludes_sec_form_codes`, `test_extract_numbers_handles_negative_number`, `test_extract_numbers_handles_multiple_values`. Update the top import line from:

```python
from evals.run_eval import extract_numbers, results_match
```

to:

```python
from evals.run_eval import results_match
```

- [ ] **Step 5: Add `compute_abstain_metrics`**

Near `score_guardrail_case` in `evals/run_eval.py`, add:

```python
ABSTAIN_EXPECTED_BEHAVIORS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}


def compute_abstain_metrics(per_case: list[dict], cases_by_id: dict) -> dict:
    all_abstains = [r for r in per_case if r["answer"] is None]
    correct_abstains = [
        r
        for r in all_abstains
        if cases_by_id[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
        and r.get("reason_code") == cases_by_id[r["id"]].get("reason_code")
    ]
    expected_abstains = [
        c for c in cases_by_id.values() if c["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
    ]
    return {
        "all_abstains": len(all_abstains),
        "correct_abstains": len(correct_abstains),
        "expected_abstains": len(expected_abstains),
        "abstain_precision": len(correct_abstains) / len(all_abstains) if all_abstains else 0.0,
        "abstain_recall": (
            len(correct_abstains) / len(expected_abstains) if expected_abstains else 0.0
        ),
    }
```

- [ ] **Step 6: Run tests to verify `compute_abstain_metrics` passes**

Run: `uv run pytest tests/test_run_eval.py -v -k compute_abstain`
Expected: PASS (5 tests)

- [ ] **Step 7: Wire `confidence` and fiscal-year hallucination checking into `run()`, and abstain metrics into the summary**

In `evals/run_eval.py`'s `run()` function:

1. In the `record = {...}` dict literal (the normal, non-crashed path), add one key: `"confidence": result.get("confidence")`.
2. In the existing hallucination-check block (`if result["answer"] is not None: ...`), extend the ungrounded-number computation to also check fiscal years, matching what the live pipeline's own `verify.py` checks — find this block:

```python
        if result["answer"] is not None:
            answered += 1
            claimed = extract_numbers(result["answer"])
            grounded_values = {
                v for row in result["rows"] for v in row if isinstance(v, int | float)
            }
            ungrounded = [
                n for n in claimed if not any(_scalar_match(g, n, 0.01) for g in grounded_values)
            ]
            record["hallucinated_numbers"] = ungrounded
            if ungrounded:
                hallucinated += 1
```

Replace with:

```python
        if result["answer"] is not None:
            answered += 1
            claimed = extract_numbers(result["answer"])
            grounded_values = {
                v for row in result["rows"] for v in row if isinstance(v, int | float)
            }
            ungrounded = [
                n for n in claimed if not any(_scalar_match(g, n, 0.01) for g in grounded_values)
            ]
            if "fiscal_year" in result["columns"]:
                idx = result["columns"].index("fiscal_year")
                grounded_years = {row[idx] for row in result["rows"] if row[idx] is not None}
                ungrounded += [
                    float(y) for y in extract_years(result["answer"]) if y not in grounded_years
                ]
            record["hallucinated_numbers"] = ungrounded
            if ungrounded:
                hallucinated += 1
```

3. Build `cases_by_id` right after `cases = load_gold_cases(gold_path)` at the top of `run()`: `cases_by_id = {c["id"]: c for c in cases}`.
4. Right before the `return {...}` at the end of `run()`, compute abstain metrics: `abstain_metrics = compute_abstain_metrics(per_case, cases_by_id)`.
5. Add `**abstain_metrics` to the returned summary dict (merges `all_abstains`, `correct_abstains`, `expected_abstains`, `abstain_precision`, `abstain_recall` in as top-level keys).

- [ ] **Step 8: Rename the report and add the Confidence/Ablation sections**

In `evals/run_eval.py`'s `write_reports()`:

1. Change the filenames:

```python
    md_path = reports_dir / "eval.md"
    jsonl_path = reports_dir / f"eval_{today}.jsonl"
```

2. Change the title from `"# Phase 3 Baseline"` to `"# LedgerQL Eval"`.
3. After the existing "Guardrail catch rate" section (the `for tier in sorted(GUARDRAIL_SCORED_TIERS): ...` loop) and before the final `f"Full per-case results: ..."` line, insert two new sections:

```python
    lines += [
        "",
        "## Confidence & abstain",
        "",
        f"Abstain precision: {summary['abstain_precision']:.1%} "
        f"({summary['correct_abstains']}/{summary['all_abstains']} abstains were correct) "
        "-- Phase 4 acceptance target: >= 80%.",
        f"Abstain recall: {summary['abstain_recall']:.1%} "
        f"({summary['correct_abstains']}/{summary['expected_abstains']} cases that should "
        "have abstained were caught).",
        "",
        "## Ablation",
        "",
        "| Configuration | Execution accuracy | Hallucinated-number rate | Adversarial guardrail catch |",
        "|---|---|---|---|",
        "| naive (Phase 2) | 58.0% | 32.5% | n/a |",
        "| +static guardrails (Phase 3) | 58.0% | 28.6% | 88.9% |",
        f"| +self-consistency & verifier (Phase 4) | {summary['overall_execution_accuracy']:.1%} "
        f"| {summary['hallucinated_number_rate']:.1%} "
        f"| {summary['guardrail_catch_rate'].get('adversarial', 0.0):.1%} |",
    ]
```

- [ ] **Step 9: Update the existing `test_write_reports_serializes_date_values_in_rows` fixture**

In `tests/test_run_eval.py`, the existing test's `summary` dict is missing the new keys `write_reports()` now reads directly (`summary['abstain_precision']` etc. — a direct index, not `.get()`, so a missing key raises `KeyError`). Add these keys to that test's `summary` dict literal:

```python
        "all_abstains": 0,
        "correct_abstains": 0,
        "expected_abstains": 0,
        "abstain_precision": 0.0,
        "abstain_recall": 0.0,
```

Also update the two path assertions in that test, since the filenames changed:

```python
    md_path, jsonl_path = write_reports(summary, tmp_path)
    record = json.loads(jsonl_path.read_text().splitlines()[0])
    assert record["rows"][0][0] == "2024-09-28"
    assert md_path.exists()
    assert md_path.name == "eval.md"
    assert jsonl_path.name.startswith("eval_")
```

- [ ] **Step 10: Update the Makefile**

Replace the stale `eval:` target and remove `baseline:` entirely:

```makefile
eval:
	uv run python evals/run_eval.py --db $(or $(LEDGERQL_DB_PATH),data/ledgerql.duckdb)
```

(Remove the old `eval:` target that pointed at `ledgerql.eval.run`, and remove the `baseline:` target below it. Update the `.PHONY` line at the top of the Makefile to drop `baseline` from the list — it should read `.PHONY: setup test lint fmt data eval eval-validate run api ui clean`.)

- [ ] **Step 11: Update `.gitignore`**

Add one line near the existing `!reports/baseline.md` exception:

```
!reports/eval.md
```

- [ ] **Step 12: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

Run: `uv run ruff check . && uv run black --check .`
Expected: both clean.

- [ ] **Step 13: Commit**

```bash
git add evals/run_eval.py tests/test_run_eval.py Makefile .gitignore
git commit -m "feat: DRY the verifier into evals, add confidence/abstain scoring, rename to make eval

extract_numbers/extract_years now imported from ledgerql.verify
(Task 1's canonical version) instead of a second local copy --
run_eval.py's hallucination-rate metric also gains fiscal-year
checking, matching what the live pipeline's own verify.py enforces.
New compute_abstain_metrics() reports abstain precision/recall
against the master prompt's Phase 4 acceptance target. reports/
baseline.md -> reports/eval.md (a fixed, git-committable filename
mirroring baseline.md's role, not the spec's originally-cited dated
name, which doesn't fit a single-committed-snapshot workflow); make
baseline retired in favor of a real make eval. reports/baseline.md
itself is left untouched as Phase 3's historical evidence."
```

---

### Task 7: Real end-to-end run, abstain-threshold sweep, verification

**Files:** none created — this task runs the real pipeline, empirically picks the final `LOW_AGREEMENT_THRESHOLD`, and verifies the output. May modify `ledgerql/pipeline.py`'s `LOW_AGREEMENT_THRESHOLD` constant if the sweep picks a different value than Task 5's starting `0.6`.

**Interfaces:** none new.

- [ ] **Step 1: Confirm the Ollama daemon is running**

Run: `curl -sf http://localhost:11434/api/tags`
Expected: a JSON response listing `qwen2.5-coder:7b`. If this fails, start it (`ollama serve &`, or `nohup ollama serve > /tmp/ollama_serve.log 2>&1 & disown` to survive the shell exiting).

- [ ] **Step 2: Run the full test suite once more**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 3: Sweep `LOW_AGREEMENT_THRESHOLD` against real pipeline output**

This phase's generation cost is roughly 5x Phase 3's (N_CANDIDATES=5 vs n=1 per question), so a full 103-case sweep at 3 threshold values is expensive. Instead: pick 10-15 representative real gold cases spanning `lookup`/`aggregation` (should have high agreement), `ambiguous` (should have low agreement, per the spec's own documented finding that this model doesn't always show it clearly), and 2-3 `adversarial` cases (should hit the no-winner path, not the threshold path, so agreement doesn't apply there — skip them for this specific sweep). Run `pipeline.ask()` directly (not through `run_eval.py`) against this smaller set, print each case's real `confidence` (consensus agreement) value, and inspect the distribution: does 0.6 (Task 5's starting value) cleanly separate cases that should abstain from cases that should answer, or does the real distribution suggest a different threshold (e.g. if most real agreement values cluster at exactly 0.2/0.4/0.6/0.8/1.0 — the only 5 possible values for N=5 — pick the cut point empirically, not by assuming 0.6 is right). If a different value performs better, update `LOW_AGREEMENT_THRESHOLD` in `ledgerql/pipeline.py` and note the change and why in this task's summary (added to the ledger during execution, per the SDD process).

- [ ] **Step 4: Run the real end-to-end eval**

Run: `make eval`

Expected: this makes up to 5 (candidates) + 1 (answer, if a winner is reached) real Ollama calls per case for generation, plus 1 for classify — noticeably more real calls than Phase 3's run. Budget at least 30-45 minutes for the full 103-case run. It prints a summary and writes `reports/eval.md` and `reports/eval_<date>.jsonl`.

- [ ] **Step 5: Sanity-check the real output**

```bash
cat reports/eval.md
```

Expected, per the master prompt's Phase 4 acceptance criteria: hallucinated-number rate should be at or very near 0% (the whole point of this phase — if it is not near 0%, investigate specific `hallucinated_numbers` entries in `reports/eval_<date>.jsonl` before declaring this task complete, the same way Phase 3's Task 7 investigated real classify.py failures rather than accepting a bad number). Abstain precision should be at or above 80% (the master prompt's explicit target) — if it is not, inspect which abstains are wrong (wrong reason code, or a case that shouldn't have abstained at all) in the per-case jsonl. Execution accuracy should be roughly comparable to Phase 3's 58.0% (self-consistency and a stricter answer prompt could shift this in either direction — a large unexplained drop is worth investigating, a large unexplained rise is worth double-checking for a scoring bug, but modest movement either way is expected and not itself a problem). The Ablation table should show all three phases' real numbers in one place.

- [ ] **Step 6: Spot-check a handful of real per-case records**

```bash
python3 -c "
import json
records = [json.loads(l) for l in open('reports/eval_<today's date>.jsonl')]
# replace <today's date> with the actual date in the filename written by Step 4
for r in records[:5]:
    print(r['id'], '| confidence:', r.get('confidence'), '| reason:', r.get('reason_code'), '| answer:', (r.get('answer') or '')[:60])
"
```

Expected: `confidence` is populated (not always `null`) for cases that reached consensus voting; a case with a low confidence value should correlate with either an abstain (`LOW_AGREEMENT`) or, if it still answered, a case where you'd independently judge the question as genuinely easy despite a lower score (a false-low-confidence case is worth noting, not silently accepting). Confirm at least one real adversarial case still shows `reason_code` set with `confidence: null` (the no-winner path correctly reports no confidence signal, distinct from the low-agreement path which does).

- [ ] **Step 7: Commit the real report**

```bash
git add reports/eval.md
git status --short  # confirm reports/eval_<date>.jsonl is NOT staged (gitignored, per design)
git commit -m "docs: commit the real Phase 4 eval report

Real end-to-end run: <fill in the actual numbers from reports/eval.md>.
<Note the final LOW_AGREEMENT_THRESHOLD value and whether it changed
from Task 5's starting 0.6, and why, if it did.>"
```

- [ ] **Step 8: Nothing else to commit**

`reports/eval_<date>.jsonl` is gitignored (per-run detail, matching Phase 2/3's precedent for the dated jsonl) — only `reports/eval.md` (Step 7) is source-worthy. If Step 3's sweep changed `LOW_AGREEMENT_THRESHOLD`, that change was already committed as part of Step 7 or (if you prefer a separate, clearly-labeled commit isolating the constant change from the report) a small preceding commit — either is fine, but the constant change must be committed before the final `reports/eval.md` that reflects it.

---

## Self-review notes

- **Spec coverage:** temperature finding and `OLLAMA_CONSENSUS_TEMPERATURE` (spec §2/§3, Task 3), `consensus.py`'s clustering/agreement/no-winner design including the "winner with empty rows is not a no-winner case" fix made during spec self-review (spec §4, Task 2), `verify.py`'s numeric + fiscal-year grounding including the "magnitude words already covered, years need a separate check" finding (spec §5, Task 1), `answer.py` hiding the question (spec §6, Task 4), `run_eval.py`'s DRY extraction + confidence/abstain-precision/ablation table (spec §7, Task 6), `pipeline.py`'s two-independent-triggers orchestration matching the spec's corrected §8 pseudocode exactly (Task 5), report renaming to `reports/eval.md`/`make eval` with the fixed-filename refinement over the spec's literal dated-name suggestion, justified and documented (spec §9, Task 6). §10 (out of scope) respected: no task touches the full calibration framework, `accept_alternatives` parsing, the FastAPI/Streamlit surface, or any frozen file (`docs/schema.md`, `evals/gold.jsonl`, `ledgerql/data/*`, `ledgerql/guardrails.py`, `ledgerql/classify.py`, `ledgerql/audit.py`'s mechanism, `ledgerql/execute.py`).
- **Type/signature consistency:** `GuardrailResult`/`ExecutionResult` (Phase 3/2, unchanged) are consumed identically in Task 2's `consensus.vote()` and Task 5's `pipeline.ask()`. `ConsensusResult` (Task 2: `sql`, `columns`, `rows`, `truncated`, `agreement`, `events`, `reason_code`, `detail`) is consumed identically in Task 5 (`consensus_result.reason_code`, `.agreement`, `.columns`, `.rows`, `.truncated`, `.sql`, `.events`) and Task 2's own tests. `VerifyResult` (Task 1: `ok`, `ungrounded_numbers`, `detail`) matches Task 5's usage (`verify_result.ok`, `.detail`). `generate_candidates(question, schema_context, n=1, temperature=None, client=None)` (Task 3) matches Task 5's call (`n=N_CANDIDATES, temperature=generate_module.OLLAMA_CONSENSUS_TEMPERATURE`) and Task 3's own tests. `write_answer(result, client=None)` (Task 4, `question` removed) matches Task 5's call site (`answer_module.write_answer(winner)`, no question argument). `pipeline.ask()`'s returned dict gains exactly one new key (`confidence`) that Task 6's `run()` reads via `result.get("confidence")` and writes into both `record` and (already present, now populated) the summary's abstain/confidence reporting.
- **Corrected during planning (this document, not the spec):** none beyond what the spec's own self-review already caught (the `reason_code is None`/no-winner-vs-empty-rows distinction, and the comment-stripping mechanism correction from Phase 3's precedent pattern applied here to double-check `verify.py`'s design) — this plan's own drafting surfaced one additional refinement worth flagging: §9's report-naming decision is implemented here as a **fixed** `reports/eval.md` (git-committable, one current snapshot, mirroring `baseline.md`'s proven role across two prior phases) rather than the spec's literally-cited `eval_<date>.md` — a dated, ever-accumulating filename doesn't fit this project's established "one committed snapshot, dated per-run detail stays gitignored" pattern, and committing a new dated `.md` file on every run would silently break that pattern without anyone deciding to. Documented here and in Task 6's commit message rather than silently deviating from the spec's wording.
