# Phase 2 — Naive Text-to-SQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the naive (unguardrailed) text-to-SQL pipeline — Ollama SQL generation, read-only execution, an unverified LLM-phrased answer — and score it against the real 103-case gold set to produce `reports/baseline.md`.

**Architecture:** Four small modules (`schema_index`, `generate`, `execute`, `answer`) each wrapping one stage, composed by `pipeline.ask()`. A separate `evals/run_eval.py` harness runs every gold case through the real pipeline and scores it, distinct from the user's own `evals/validate_gold.py` (which only validates the gold SQL itself).

**Tech Stack:** Python 3.12, the `ollama` Python client (already a dependency) against a local Ollama daemon running `qwen2.5-coder:7b`, DuckDB (read-only), pytest with `monkeypatch`/fake clients for unit tests.

**Spec:** [docs/superpowers/specs/2026-09-05-phase2-naive-text-to-sql-design.md](../specs/2026-09-05-phase2-naive-text-to-sql-design.md)

## Global Constraints

- Zero cost, no hosted LLM APIs — local Ollama only (master prompt hard constraints #1-#2).
- Every executed connection is read-only, always — no exceptions, not even for "no guardrails yet" cases (master prompt hard constraint #3; spec §3).
- `docs/schema.md`, `evals/gold.jsonl`, `evals/README.md`, `evals/validate_gold.py`, and everything under `ledgerql/data/` are frozen — do not modify them in this plan.
- Single-shot generation only (`n=1`) — N-sample self-consistency is Phase 4's job (spec §3).
- Model: `qwen2.5-coder:7b` (already pulled). Ollama daemon is already running locally. `data/ledgerql.duckdb` already exists and is built (500 companies, 4354 filings, 111714 financial facts) — no data rebuild needed in this plan.

---

## Verified facts this plan depends on

Confirmed directly against the real environment during design/planning (not assumed):

- **Ollama client API:** `ollama.Client(host=...).generate(model=..., system=..., prompt=..., options={...})` returns an object with a `.response` string attribute. Confirmed working end-to-end against the locally running daemon and `qwen2.5-coder:7b`.
- **`docs/schema.md`'s real H2 section titles** (exact strings, case-sensitive as written in the file): `companies`, `filings`, `financial_facts`, `Concept views`. These are the sections worth injecting into the generation prompt; the file's intro paragraph, the dual-class note under `companies`, and anything after `Concept views` (the worked SQL example) are narrative, not schema definition.
- **DuckDB read-only rejection**: `duckdb.connect(path, read_only=True)` then executing `DELETE FROM ...` raises `duckdb.InvalidInputException` with message `Cannot execute statement of type "DELETE" on database "..." which is attached in read-only mode!` — confirmed against the real database.
- **DuckDB cursor API**: `con.execute(sql)` returns a cursor-like object; `.description` is a list of tuples whose first element is the column name (or `None` if the statement has no result columns); `.fetchall()` returns `list[tuple]`.
- **Timeout + interrupt mechanism**: confirmed empirically — running a query via `concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(con.execute, sql)`, calling `future.result(timeout=N)`, catching `concurrent.futures.TimeoutError`, and calling `con.interrupt()` reliably cancels the in-flight query. The interrupted query then raises `duckdb.InterruptException` if `.result()` is called again (this plan does not call it again — the `with ThreadPoolExecutor(...)` block's own exit handles thread cleanup).
- **A concrete, verified slow query for testing the timeout path**: on an in-memory DuckDB table `t(a INTEGER)` seeded with `900` rows (`0..899`), `SELECT SUM(a.a * b.a * c.a) FROM t a, t b, t c` takes **~1.9 seconds** uninterrupted (verified by direct timing) — comfortably slower than a `0.3`-second test timeout, with wide margin against machine-speed variance, while not hanging a test suite for long if the timeout mechanism somehow fails. A bare `COUNT(*)` over the same cross join does **not** work for this purpose — DuckDB's vectorized engine optimizes a pure count over a cross join to be near-instant even at far larger scales (confirmed: a 4-way cross join of 3000 rows on `COUNT(*)` did not finish in 60+ seconds when forced to materialize via a different plan shape, while the 3-way `SUM` of a per-row product on 900 rows above completes in ~1.9s — use the `SUM` form, not `COUNT(*)`, and use the exact row count/join width given here, not an arbitrarily larger one).
- **Existing config already in `.env.example`** (reused as-is, no changes needed to these): `OLLAMA_HOST`, `OLLAMA_MODEL`, `LEDGERQL_DB_PATH`, `LEDGERQL_QUERY_TIMEOUT_SECONDS` (default `10`), `LEDGERQL_ROW_LIMIT` (default `1000`). New additions needed: `OLLAMA_TEMPERATURE=0.2`, `OLLAMA_SEED=42`.
- **The Makefile already has an `eval:` target** pointing at a nonexistent module (`ledgerql.eval.run`) — a Phase 0 placeholder for the fuller ablation/calibration framework `evals/README.md` documents. This plan does **not** touch that target; it adds a new, separate `baseline:` target.
- **`evals/gold.jsonl` is fully reconciled**: 103 cases, `python evals/validate_gold.py --db data/ledgerql.duckdb` prints `ALL HARD CHECKS PASSED` (50 `ANSWER`, 19 `ANSWER_WITH_ASSUMPTION`, 34 `ABSTAIN`). Every `gold_sql` in the file is confirmed to bind and execute against the real database.

---

## File Structure

```
ledgerql/
  schema_index.py    # rewritten: get_schema_context() reads/trims docs/schema.md
  generate.py         # rewritten: generate_candidates() calls Ollama, n=1 only
  execute.py          # rewritten: execute() -> ExecutionResult, read-only, capped, timed out
  answer.py            # rewritten: write_answer() calls Ollama with question+result
  pipeline.py          # rewritten: ask() orchestrates the above
tests/
  test_schema_index.py
  test_generate.py
  test_execute.py
  test_answer.py
  test_pipeline.py
evals/
  run_eval.py          # new: runs all 103 gold cases through pipeline.ask(), scores, reports
.env.example            # add OLLAMA_TEMPERATURE, OLLAMA_SEED
Makefile                 # add `baseline` target
reports/
  baseline.md            # generated by `make baseline`, not checked in as a template
  baseline_<date>.jsonl   # generated alongside it
```

---

### Task 1: Schema context

**Files:**
- Modify: `ledgerql/schema_index.py` (replace Phase 0 stub entirely)
- Test: `tests/test_schema_index.py`

**Interfaces:**
- Produces: `get_schema_context(schema_md_path: Path = SCHEMA_MD_PATH) -> str`. `SCHEMA_MD_PATH` is a module-level `Path` constant pointing at the real `docs/schema.md` (computed from `Path(__file__).resolve().parent.parent / "docs" / "schema.md"`, since `ledgerql/schema_index.py` is one directory below the repo root).

- [ ] **Step 1: Write the failing test**

`tests/test_schema_index.py`:

```python
from pathlib import Path

from ledgerql.schema_index import get_schema_context


def test_get_schema_context_keeps_table_sections_drops_narrative(tmp_path):
    schema_md = tmp_path / "schema.md"
    schema_md.write_text(
        "# Schema\n"
        "\n"
        "Some intro paragraph that should be dropped.\n"
        "\n"
        "## companies\n"
        "\n"
        "One row per company.\n"
        "\n"
        "| Column | Type |\n"
        "|---|---|\n"
        "| cik | INTEGER |\n"
        "\n"
        "## filings\n"
        "\n"
        "Filing info.\n"
        "\n"
        "## financial_facts\n"
        "\n"
        "Facts info.\n"
        "\n"
        "## Concept views\n"
        "\n"
        "View info.\n"
        "\n"
        "## Some Other Section\n"
        "\n"
        "This should be dropped.\n"
    )
    context = get_schema_context(schema_md)
    assert "cik" in context
    assert "Filing info." in context
    assert "Facts info." in context
    assert "View info." in context
    assert "Some intro paragraph" not in context
    assert "Some Other Section" not in context
    assert "This should be dropped" not in context


def test_get_schema_context_default_path_reads_real_schema():
    context = get_schema_context()
    assert "v_revenue" in context
    assert "v_net_income" in context
    assert "v_total_assets" in context
    assert "v_cash" in context
    assert len(context) > 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema_index.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_schema_context'`

- [ ] **Step 3: Write the implementation**

`ledgerql/schema_index.py`:

```python
"""Stage 2: schema retrieval.

Phase 2 injects the full analyst schema into every generation prompt --
the schema is small (3 tables + 4 views) so there's nothing to
selectively retrieve yet. Reads docs/schema.md and keeps only the H2
sections that define tables/views, dropping narrative sections (the
intro, the dual-class note, the worked SQL example) that read well for
a human but don't improve SQL correctness and cost tokens.
"""

from pathlib import Path

SCHEMA_MD_PATH = Path(__file__).resolve().parent.parent / "docs" / "schema.md"

KEPT_SECTIONS = {"companies", "filings", "financial_facts", "concept views"}


def get_schema_context(schema_md_path: Path = SCHEMA_MD_PATH) -> str:
    text = schema_md_path.read_text()
    sections = _split_into_h2_sections(text)
    kept = [body for title, body in sections if title.strip().lower() in KEPT_SECTIONS]
    return "\n\n".join(kept).strip()


def _split_into_h2_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = [line]
        elif current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schema_index.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/schema_index.py tests/test_schema_index.py
git commit -m "feat: implement schema context retrieval for Phase 2 prompts

Reads docs/schema.md and keeps only the table/view definition
sections, dropping narrative prose that costs tokens without
improving SQL correctness."
```

---

### Task 2: SQL generation via Ollama

**Files:**
- Modify: `ledgerql/generate.py` (replace Phase 0 stub entirely)
- Test: `tests/test_generate.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (takes `schema_context: str` as a plain argument — callers pass `schema_index.get_schema_context()`'s return value).
- Produces: `generate_candidates(question: str, schema_context: str, n: int = 1, client: ollama.Client | None = None) -> list[str]`. Raises `NotImplementedError` if `n != 1`. Module constants `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_TEMPERATURE`, `OLLAMA_SEED` (all read from environment variables at import time, with the defaults given in Task 6's `.env.example` additions).

- [ ] **Step 1: Write the failing tests**

`tests/test_generate.py`:

```python
import pytest

from ledgerql import generate


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
    generate.generate_candidates("What was Apple's revenue?", "SCHEMA_TEXT_HERE", n=1, client=client)
    assert "What was Apple's revenue?" in client.last_call["prompt"]
    assert "SCHEMA_TEXT_HERE" in client.last_call["prompt"]


def test_generate_candidates_rejects_n_other_than_one():
    client = _FakeClient("SELECT 1;")
    with pytest.raises(NotImplementedError):
        generate.generate_candidates("q", "schema", n=2, client=client)


def test_generate_candidates_returns_plain_sql_unchanged():
    client = _FakeClient("SELECT value FROM v_revenue WHERE ticker='AAPL'")
    result = generate.generate_candidates("q", "schema", n=1, client=client)
    assert result == ["SELECT value FROM v_revenue WHERE ticker='AAPL'"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_generate.py -v`
Expected: FAIL (functions/constants don't exist yet on the Phase 0 stub)

- [ ] **Step 3: Write the implementation**

`ledgerql/generate.py`:

```python
"""Stage 3: SQL generation.

Calls the local Ollama model (default qwen2.5-coder:7b) to produce SQL
given the question and the schema context. Phase 2 is single-shot
(n=1) -- self-consistency across N candidates is Phase 4's job, so n=1
is the only supported value here.
"""

import os
import re

import ollama

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
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
    client: ollama.Client | None = None,
) -> list[str]:
    if n != 1:
        raise NotImplementedError(
            "Phase 2 only supports single-shot generation (n=1); "
            "N-sample self-consistency is Phase 4's job."
        )
    client = client or ollama.Client(host=OLLAMA_HOST)
    prompt = f"Schema:\n{schema_context}\n\nQuestion: {question}\n\nSQL:"
    response = client.generate(
        model=OLLAMA_MODEL,
        system=SYSTEM_PROMPT,
        prompt=prompt,
        options={"temperature": OLLAMA_TEMPERATURE, "seed": OLLAMA_SEED},
    )
    return [_strip_fences(response.response)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_generate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/generate.py tests/test_generate.py
git commit -m "feat: implement Ollama SQL generation for Phase 2

Single-shot (n=1) generation against qwen2.5-coder:7b, with
temperature and seed both configurable via env vars for a
reproducible baseline despite non-zero temperature."
```

---

### Task 3: Read-only, capped, timed-out execution

**Files:**
- Modify: `ledgerql/execute.py` (replace Phase 0 stub entirely)
- Test: `tests/test_execute.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `@dataclass ExecutionResult` (`columns: list[str]`, `rows: list[tuple]`, `error: str | None`, `truncated: bool`, with `columns`/`rows` defaulting to empty lists and `error`/`truncated` defaulting to `None`/`False`); `execute(sql: str, db_path: str = DB_PATH, timeout_seconds: float = QUERY_TIMEOUT_SECONDS, row_limit: int = ROW_LIMIT) -> ExecutionResult`. Module constants `DB_PATH`, `ROW_LIMIT`, `QUERY_TIMEOUT_SECONDS` read from `LEDGERQL_DB_PATH`, `LEDGERQL_ROW_LIMIT`, `LEDGERQL_QUERY_TIMEOUT_SECONDS` env vars (all already defined in `.env.example` from Phase 0, defaults `"data/ledgerql.duckdb"`, `1000`, `10`).

- [ ] **Step 1: Write the failing tests**

`tests/test_execute.py`:

```python
import duckdb

from ledgerql import execute


def _make_db(tmp_path, rows):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    con.close()
    return str(db_path)


def test_execute_returns_columns_and_rows(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x"), (2, "y")])
    result = execute.execute("SELECT a, b FROM t ORDER BY a", db_path=db_path)
    assert result.error is None
    assert result.columns == ["a", "b"]
    assert result.rows == [(1, "x"), (2, "y")]
    assert result.truncated is False


def test_execute_rejects_write_statements(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x")])
    result = execute.execute("DELETE FROM t", db_path=db_path)
    assert result.error is not None
    assert "read-only mode" in result.error


def test_execute_truncates_to_row_limit(tmp_path):
    db_path = _make_db(tmp_path, [(i, str(i)) for i in range(10)])
    result = execute.execute("SELECT a FROM t ORDER BY a", db_path=db_path, row_limit=3)
    assert result.error is None
    assert result.rows == [(0,), (1,), (2,)]
    assert result.truncated is True


def test_execute_does_not_flag_truncation_when_under_limit(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x"), (2, "y")])
    result = execute.execute("SELECT a FROM t", db_path=db_path, row_limit=1000)
    assert result.truncated is False


def test_execute_reports_syntax_errors(tmp_path):
    db_path = _make_db(tmp_path, [(1, "x")])
    result = execute.execute("NOT VALID SQL AT ALL", db_path=db_path)
    assert result.error is not None
    assert result.rows == []


def test_execute_times_out_on_slow_query(tmp_path):
    db_path = tmp_path / "slow.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE t (a INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(900)])
    con.close()

    result = execute.execute(
        "SELECT SUM(a.a * b.a * c.a) FROM t a, t b, t c",
        db_path=str(db_path),
        timeout_seconds=0.3,
    )
    assert result.error is not None
    assert "timed out" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_execute.py -v`
Expected: FAIL (Phase 0 stub's `execute(sql)` has the wrong signature and returns `None`)

- [ ] **Step 3: Write the implementation**

`ledgerql/execute.py`:

```python
"""Stage 5: execution.

Runs a SQL statement against a read-only DuckDB connection with a
timeout and a row-count cap. This is baseline infrastructure hygiene,
not a guardrail: Phase 2 has no AST validation, no cost estimation, no
schema allowlisting (those are Phase 3's guardrails.py) -- but the
connection is read-only from day one, consistent with the master
prompt's non-negotiable constraint #3, and results are capped so a
pathological query can't exhaust memory or blow the answer-generation
prompt's context.
"""

import concurrent.futures
import os
from dataclasses import dataclass, field

import duckdb

DB_PATH = os.environ.get("LEDGERQL_DB_PATH", "data/ledgerql.duckdb")
ROW_LIMIT = int(os.environ.get("LEDGERQL_ROW_LIMIT", "1000"))
QUERY_TIMEOUT_SECONDS = float(os.environ.get("LEDGERQL_QUERY_TIMEOUT_SECONDS", "10"))


@dataclass
class ExecutionResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False


def execute(
    sql: str,
    db_path: str = DB_PATH,
    timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
    row_limit: int = ROW_LIMIT,
) -> ExecutionResult:
    try:
        con = duckdb.connect(db_path, read_only=True)
    except Exception as e:  # noqa: BLE001
        return ExecutionResult(error=str(e))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(con.execute, sql)
            try:
                cursor = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                con.interrupt()
                return ExecutionResult(error=f"query timed out after {timeout_seconds}s")
            except Exception as e:  # noqa: BLE001
                return ExecutionResult(error=str(e))

            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

        truncated = len(rows) > row_limit
        if truncated:
            rows = rows[:row_limit]
        return ExecutionResult(columns=columns, rows=rows, truncated=truncated)
    except Exception as e:  # noqa: BLE001
        return ExecutionResult(error=str(e))
    finally:
        con.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_execute.py -v`
Expected: PASS (6 tests). The timeout test takes at least 0.3s to run (that's expected).

- [ ] **Step 5: Commit**

```bash
git add ledgerql/execute.py tests/test_execute.py
git commit -m "feat: implement read-only, capped, timed-out SQL execution

Read-only connection always (not a guardrail feature -- basic safety
per the master prompt's non-negotiable constraint #3), row-limit
truncation, and a thread+interrupt-based query timeout, verified
against a real slow query."
```

---

### Task 4: Unverified answer generation

**Files:**
- Modify: `ledgerql/answer.py` (replace Phase 0 stub entirely)
- Test: `tests/test_answer.py`

**Interfaces:**
- Consumes: `ExecutionResult` from Task 3 (`ledgerql.execute.ExecutionResult`, fields `columns: list[str]`, `rows: list[tuple]`).
- Produces: `write_answer(question: str, result: ExecutionResult, client: ollama.Client | None = None) -> str`. Reuses the same `OLLAMA_HOST`/`OLLAMA_MODEL`/`OLLAMA_TEMPERATURE`/`OLLAMA_SEED` env-var pattern as Task 2 (each module reads its own copies of these constants at import time — no shared config module exists yet, and creating one now for four identical `os.environ.get` lines would be premature abstraction for two call sites).

- [ ] **Step 1: Write the failing tests**

`tests/test_answer.py`:

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


def test_write_answer_includes_question_and_result_in_prompt():
    client = _FakeClient("Apple's fiscal 2024 revenue was $391.0 billion.")
    result = ExecutionResult(columns=["value"], rows=[(391035000000,)])
    answer_text = answer.write_answer("What was Apple's revenue?", result, client=client)
    assert answer_text == "Apple's fiscal 2024 revenue was $391.0 billion."
    assert "What was Apple's revenue?" in client.last_call["prompt"]
    assert "391035000000" in client.last_call["prompt"]


def test_write_answer_handles_empty_result():
    client = _FakeClient("No matching data was found.")
    result = ExecutionResult(columns=["value"], rows=[])
    answer_text = answer.write_answer("q", result, client=client)
    assert answer_text == "No matching data was found."
    assert "(no rows)" in client.last_call["prompt"]


def test_write_answer_passes_temperature_and_seed():
    client = _FakeClient("answer")
    result = ExecutionResult(columns=["x"], rows=[(1,)])
    answer.write_answer("q", result, client=client)
    assert client.last_call["options"]["temperature"] == answer.OLLAMA_TEMPERATURE
    assert client.last_call["options"]["seed"] == answer.OLLAMA_SEED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_answer.py -v`
Expected: FAIL (Phase 0 stub's `write_answer` raises `NotImplementedError`)

- [ ] **Step 3: Write the implementation**

`ledgerql/answer.py`:

```python
"""Stage 7a: answer generation (Phase 2 version).

Phase 2 shows the model both the question and the executed result and
asks for a plain-English answer -- unverified, no grounding check.
Phase 4 replaces this with a stricter version that hides the question
(to force grounding in the data alone) and adds a numeric verifier;
this function's behavior is expected to change substantially then --
that evolution is the point of the ablation story, not a defect to
avoid by over-building Phase 2 now.
"""

import os

import ollama

from ledgerql.execute import ExecutionResult

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_SEED = int(os.environ.get("OLLAMA_SEED", "42"))

SYSTEM_PROMPT = (
    "You answer questions about company financials using only the data "
    "table provided below. Write one or two plain-English sentences. "
    "State any unit or fiscal year explicitly."
)


def _format_result(result: ExecutionResult) -> str:
    header = "\t".join(result.columns)
    if not result.rows:
        return f"{header}\n(no rows)"
    body = "\n".join("\t".join(str(v) for v in row) for row in result.rows)
    return f"{header}\n{body}"


def write_answer(
    question: str,
    result: ExecutionResult,
    client: ollama.Client | None = None,
) -> str:
    client = client or ollama.Client(host=OLLAMA_HOST)
    table_text = _format_result(result)
    prompt = f"Question: {question}\n\nResult:\n{table_text}\n\nAnswer:"
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
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/answer.py tests/test_answer.py
git commit -m "feat: implement unverified answer generation for Phase 2

Shows the model both question and result and asks for plain English,
no grounding check -- Phase 4 adds the verifier and question-hiding
technique; this is the deliberate 'before' half of that comparison."
```

---

### Task 5: Pipeline orchestration

**Files:**
- Modify: `ledgerql/pipeline.py` (replace Phase 0 stub entirely)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `schema_index.get_schema_context() -> str` (Task 1); `generate.generate_candidates(question, schema_context, n=1) -> list[str]` (Task 2); `execute.execute(sql) -> ExecutionResult` (Task 3); `answer.write_answer(question, result) -> str` (Task 4).
- Produces: `ask(question: str) -> dict` with keys `question: str`, `sql: str`, `columns: list[str]`, `rows: list[tuple]`, `truncated: bool`, `error: str | None`, `answer: str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`:

```python
from ledgerql import answer as answer_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import pipeline
from ledgerql.execute import ExecutionResult


def test_ask_orchestrates_generate_execute_answer(monkeypatch):
    monkeypatch.setattr(
        generate_module, "generate_candidates", lambda q, s, n=1: ["SELECT 1"]
    )
    monkeypatch.setattr(
        execute_module, "execute", lambda sql: ExecutionResult(columns=["x"], rows=[(1,)])
    )
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "The value is 1.")

    result = pipeline.ask("what is 1?")

    assert result["question"] == "what is 1?"
    assert result["sql"] == "SELECT 1"
    assert result["columns"] == ["x"]
    assert result["rows"] == [(1,)]
    assert result["truncated"] is False
    assert result["error"] is None
    assert result["answer"] == "The value is 1."


def test_ask_skips_answer_generation_on_execution_error(monkeypatch):
    monkeypatch.setattr(generate_module, "generate_candidates", lambda q, s, n=1: ["BAD SQL"])
    monkeypatch.setattr(execute_module, "execute", lambda sql: ExecutionResult(error="syntax error"))
    calls = []
    monkeypatch.setattr(
        answer_module, "write_answer", lambda q, r: calls.append(1) or "should not be called"
    )

    result = pipeline.ask("bad question")

    assert result["error"] == "syntax error"
    assert result["answer"] is None
    assert calls == []


def test_ask_uses_real_schema_context(monkeypatch):
    captured = {}

    def fake_generate(question, schema_context, n=1):
        captured["schema_context"] = schema_context
        return ["SELECT 1"]

    monkeypatch.setattr(generate_module, "generate_candidates", fake_generate)
    monkeypatch.setattr(execute_module, "execute", lambda sql: ExecutionResult(columns=["x"], rows=[(1,)]))
    monkeypatch.setattr(answer_module, "write_answer", lambda q, r: "answer")

    pipeline.ask("any question")

    assert "v_revenue" in captured["schema_context"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL (Phase 0 stub's `ask` raises `NotImplementedError`)

- [ ] **Step 3: Write the implementation**

`ledgerql/pipeline.py`:

```python
"""Orchestrates the Phase 2 naive pipeline: schema -> generate -> execute -> answer.

No classification/guardrails (Phase 3), no self-consistency (Phase 4),
no confidence/abstain -- Phase 2 attempts to answer every question,
including ones a later phase should refuse. That's the deliberate
"before" baseline the eval harness in evals/run_eval.py measures.
"""

from ledgerql import answer as answer_module
from ledgerql import execute as execute_module
from ledgerql import generate as generate_module
from ledgerql import schema_index


def ask(question: str) -> dict:
    schema_context = schema_index.get_schema_context()
    sql = generate_module.generate_candidates(question, schema_context, n=1)[0]
    result = execute_module.execute(sql)

    base = {
        "question": question,
        "sql": sql,
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "error": result.error,
    }

    if result.error is not None:
        return {**base, "answer": None}

    answer_text = answer_module.write_answer(question, result)
    return {**base, "answer": answer_text}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ledgerql/pipeline.py tests/test_pipeline.py
git commit -m "feat: orchestrate the Phase 2 naive pipeline end to end

schema -> generate -> execute -> answer, with no guardrails,
consensus, or confidence -- attempts every question naively,
including ones later phases should refuse."
```

---

### Task 6: Eval harness and `reports/baseline.md`

**Files:**
- Create: `evals/run_eval.py`
- Modify: `.env.example` (add `OLLAMA_TEMPERATURE=0.2`, `OLLAMA_SEED=42`)
- Modify: `Makefile` (add `baseline` target)
- Modify: `.gitignore` (add `reports/*.jsonl` — confirmed `reports/*.md` is already ignored via `.gitignore:34`, but that pattern doesn't cover the new `.jsonl` per-case output; both are generated artifacts and should be treated the same way)
- Test: `tests/test_run_eval.py`

**Interfaces:**
- Consumes: `pipeline.ask(question) -> dict` (Task 5, exact return shape given there).
- Produces: `extract_numbers(text: str) -> list[float]`; `results_match(gold_rows: list[tuple], pred_rows: list[tuple], compare: str, tolerance: float = 1e-6) -> bool`; `load_gold_cases(path: Path) -> list[dict]`; `run(gold_path: Path, db_path: str) -> dict` (returns a summary dict with the same shape written to `reports/baseline.md`/`.jsonl`); a `if __name__ == "__main__":` CLI entrypoint accepting `--gold` and `--db` (mirroring `evals/validate_gold.py`'s own argument names for consistency).

- [ ] **Step 1: Write the failing tests**

`tests/test_run_eval.py`:

```python
import duckdb

from evals.run_eval import extract_numbers, results_match


def test_extract_numbers_handles_plain_integer():
    assert extract_numbers("The value is 391035000000.") == [391035000000.0]


def test_extract_numbers_handles_billions_word():
    assert extract_numbers("Revenue was $391.0 billion.") == [391000000000.0]


def test_extract_numbers_handles_percent():
    numbers = extract_numbers("Growth was 6.43%.")
    assert numbers == [6.43]


def test_extract_numbers_excludes_plausible_years():
    # A bare 4-digit number in the 2000-2099 range reads as a fiscal
    # year, not a data value, and must not be treated as an ungrounded
    # numeric claim.
    numbers = extract_numbers("This is fiscal year 2024 data.")
    assert numbers == []


def test_extract_numbers_handles_multiple_values():
    numbers = extract_numbers("Revenue was $391.0 billion and net income was $93.7 billion.")
    assert numbers == [391000000000.0, 93700000000.0]


def test_results_match_scalar_within_tolerance():
    assert results_match([(391035000000.0,)], [(391035000000.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(391035000001.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(1.0,)], "scalar") is False


def test_results_match_scalar_respects_custom_tolerance():
    assert results_match([(100.0,)], [(105.0,)], "scalar", tolerance=0.05) is True
    assert results_match([(100.0,)], [(106.0,)], "scalar", tolerance=0.05) is False


def test_results_match_empty():
    assert results_match([], [], "empty") is True
    assert results_match([], [(1,)], "empty") is False


def test_results_match_set_ignores_order():
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], "set") is True
    assert results_match([(1, "a")], [(2, "b")], "set") is False


def test_results_match_ordered_requires_same_order():
    assert results_match([(1,), (2,)], [(1,), (2,)], "ordered") is True
    assert results_match([(1,), (2,)], [(2,), (1,)], "ordered") is False


def test_results_match_scalar_or_null_treats_both_none_as_match():
    assert results_match([(None,)], [(None,)], "scalar_or_null") is True
    assert results_match([(None,)], [(5.0,)], "scalar_or_null") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_run_eval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.run_eval'`

- [ ] **Step 3: Add `.env.example` entries**

In `.env.example`, under the `# Ollama` section, add two lines after `OLLAMA_MODEL=qwen2.5-coder:7b`:

```
OLLAMA_TEMPERATURE=0.2
OLLAMA_SEED=42
```

- [ ] **Step 4: Write `evals/run_eval.py`**

```python
"""Runs every case in evals/gold.jsonl through the real Phase 2 pipeline
and scores it -- distinct from evals/validate_gold.py, which only
validates that the gold SQL itself is well-formed and binds/executes;
this script actually exercises pipeline.ask() and compares its output
to gold.

Run: python evals/run_eval.py --db data/ledgerql.duckdb
Writes: reports/baseline.md and reports/baseline_<date>.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

from ledgerql import generate as generate_module
from ledgerql import pipeline

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# A bare 4-digit number that reads as a plausible fiscal/calendar year
# (2000-2099) is excluded -- these appear constantly in grounded,
# correct answers ("fiscal year 2024") and are not data values that
# need to trace back to the executed result set.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        raw_digits, word = match.groups()
        digits = raw_digits.replace(",", "")
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


def _scalar_match(gold_val, pred_val, tolerance: float) -> bool:
    if gold_val is None or pred_val is None:
        return gold_val == pred_val
    try:
        return abs(float(pred_val) - float(gold_val)) <= max(abs(float(gold_val)) * tolerance, 1e-9)
    except (TypeError, ValueError):
        return gold_val == pred_val


def results_match(
    gold_rows: list[tuple], pred_rows: list[tuple], compare: str, tolerance: float = 1e-6
) -> bool:
    if compare == "empty":
        return len(pred_rows) == 0
    if compare in ("scalar", "count", "scalar_or_null"):
        if len(pred_rows) != 1 or len(pred_rows[0]) != 1:
            return False
        gold_val = gold_rows[0][0] if gold_rows else None
        return _scalar_match(gold_val, pred_rows[0][0], tolerance)
    if compare == "set":
        return set(map(tuple, gold_rows)) == set(map(tuple, pred_rows))
    if compare == "ordered":
        return list(map(tuple, gold_rows)) == list(map(tuple, pred_rows))
    return False


def load_gold_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text().splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run(gold_path: Path, db_path: str) -> dict:
    cases = load_gold_cases(gold_path)
    con = duckdb.connect(db_path, read_only=True)

    per_case = []
    tier_correct: dict[str, int] = defaultdict(int)
    tier_total: dict[str, int] = defaultdict(int)
    hallucinated = 0
    answered = 0

    for case in cases:
        result = pipeline.ask(case["question"])
        record = {
            "id": case["id"],
            "tier": case["tier"],
            "expected": case["expected"],
            "generated_sql": result["sql"],
            "execution_error": result["error"],
            "answer": result["answer"],
        }

        if case["expected"] == "ANSWER":
            tier_total[case["tier"]] += 1
            correct = False
            if result["error"] is None:
                gold_rows = con.execute(case["gold_sql"]).fetchall()
                tolerance = case.get("tolerance", 1e-6)
                correct = results_match(gold_rows, result["rows"], case["compare"], tolerance)
            record["execution_correct"] = correct
            if correct:
                tier_correct[case["tier"]] += 1

        if result["answer"]:
            answered += 1
            claimed = extract_numbers(result["answer"])
            grounded_values = {v for row in result["rows"] for v in row if isinstance(v, (int, float))}
            ungrounded = [
                n for n in claimed
                if not any(_scalar_match(g, n, 0.01) for g in grounded_values)
            ]
            record["hallucinated_numbers"] = ungrounded
            if ungrounded:
                hallucinated += 1

        per_case.append(record)

    con.close()

    answer_cases = [c for c in cases if c["expected"] == "ANSWER"]
    overall_accuracy = (
        sum(tier_correct.values()) / len(answer_cases) if answer_cases else 0.0
    )
    non_answer_cases = [c for c in cases if c["expected"] != "ANSWER"]
    non_answer_records = [r for r in per_case if r["expected"] != "ANSWER"]
    non_answer_attempted = sum(1 for r in non_answer_records if r["answer"] is not None)
    non_answer_errored = sum(1 for r in non_answer_records if r["execution_error"] is not None)

    return {
        "overall_execution_accuracy": overall_accuracy,
        "per_tier_accuracy": {
            tier: tier_correct[tier] / tier_total[tier] for tier in tier_total
        },
        "hallucinated_number_rate": hallucinated / answered if answered else 0.0,
        "answered_count": answered,
        "non_answer_case_count": len(non_answer_cases),
        "non_answer_attempted": non_answer_attempted,
        "non_answer_errored": non_answer_errored,
        "per_case": per_case,
    }


def write_reports(summary: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    md_path = reports_dir / "baseline.md"
    jsonl_path = reports_dir / f"baseline_{today}.jsonl"

    with jsonl_path.open("w") as f:
        for record in summary["per_case"]:
            f.write(json.dumps(record) + "\n")

    lines = [
        "# Phase 2 Baseline",
        "",
        f"Date: {today}",
        f"Model: {generate_module.OLLAMA_MODEL}",
        "",
        "## Execution accuracy",
        "",
        f"Overall (on 'ANSWER'-expected cases): "
        f"{summary['overall_execution_accuracy']:.1%}",
        "",
        "| Tier | Accuracy |",
        "|---|---|",
    ]
    for tier, acc in sorted(summary["per_tier_accuracy"].items()):
        lines.append(f"| {tier} | {acc:.1%} |")
    lines += [
        "",
        "## Hallucinated-number rate",
        "",
        f"{summary['hallucinated_number_rate']:.1%} of "
        f"{summary['answered_count']} answered cases stated a number not "
        "present in that query's own executed result.",
        "",
        "## Non-ANSWER cases (ABSTAIN / ANSWER_WITH_ASSUMPTION)",
        "",
        f"{summary['non_answer_case_count']} cases where a guardrail-aware "
        "system should abstain or state an assumption. Phase 2 has no "
        "abstain logic, so this section is descriptive, not scored:",
        "",
        f"- Attempted an answer anyway: {summary['non_answer_attempted']}",
        f"- Errored during execution (e.g. adversarial DML hitting the "
        f"read-only connection): {summary['non_answer_errored']}",
        "",
        f"Full per-case results: `{jsonl_path.name}`",
        "",
    ]
    md_path.write_text("\n".join(lines))
    return md_path, jsonl_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    args = ap.parse_args()

    summary = run(Path(args.gold), args.db)
    md_path, jsonl_path = write_reports(summary, Path("reports"))
    print(f"Wrote {md_path} and {jsonl_path}")
    print(f"Overall execution accuracy: {summary['overall_execution_accuracy']:.1%}")
    print(f"Hallucinated-number rate: {summary['hallucinated_number_rate']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add the Makefile target**

In `Makefile`, add a new target near the existing `eval:` target (do not modify `eval:` itself):

```makefile
baseline:
	uv run python evals/run_eval.py --db $(or $(LEDGERQL_DB_PATH),data/ledgerql.duckdb)
```

- [ ] **Step 6: Update `.gitignore`**

In `.gitignore`, near the existing `reports/*.md` / `!reports/.gitkeep` lines, add:

```
reports/*.jsonl
```

- [ ] **Step 7: Run the new unit tests to verify they pass**

Run: `uv run pytest tests/test_run_eval.py -v`
Expected: PASS (11 tests) — these test `extract_numbers`/`results_match` in isolation and do not touch the real database or Ollama.

- [ ] **Step 8: Commit**

```bash
git add evals/run_eval.py tests/test_run_eval.py .env.example Makefile .gitignore
git commit -m "feat: add Phase 2 eval harness scoring against the gold set

Runs every gold case through the real pipeline, scores execution
accuracy on the 50 ANSWER cases and hallucinated-number rate across
all answered cases, and writes reports/baseline.md +
reports/baseline_<date>.jsonl. New make baseline target, separate
from the eval target reserved for the fuller ablation framework.
Both report artifact types are gitignored, consistent with the
existing reports/*.md treatment."
```

---

### Task 7: Real end-to-end baseline run

**Files:** none created — this task runs the pipeline for real and verifies the output.

**Interfaces:** none new.

- [ ] **Step 1: Run the full test suite once more**

Run: `uv run pytest -v`
Expected: all tests pass (Phase 1's tests plus this plan's new ones).

- [ ] **Step 2: Run the real baseline end to end**

Run: `make baseline`

Expected: this makes 103 x 2 real Ollama calls (one generation + one answer call per case, skipping the answer call for any case whose generated SQL errors) against the locally running `qwen2.5-coder:7b`. This will take a while — budget at least 10-20 minutes for 103 cases at roughly single-digit seconds per call on Apple Silicon CPU/GPU inference; do not treat a long-running command as stuck prematurely. It prints a final summary and writes `reports/baseline.md` and `reports/baseline_<date>.jsonl`.

- [ ] **Step 3: Sanity-check the real output**

```bash
cat reports/baseline.md
```

Expected: an execution accuracy well above 0% but very unlikely to be 100% (this is a naive, unguardrailed 7B local model against real multi-table SQL, including joins, subqueries, and CTEs) — a number anywhere from roughly 30% to 70% would be a plausible, honest baseline. If the number is exactly 0% or the report shows every single case erroring out, that is a real bug to investigate (e.g., a schema-context formatting problem, a model/host misconfiguration, or a bug in `results_match`) — do not report a real run with 0% accuracy as "done" without diagnosing why. Similarly, sanity-check a handful of individual cases in `reports/baseline_<date>.jsonl` by eye: does the generated SQL for a simple case like `L01` ("What was Apple's revenue in fiscal year 2024?") look like a plausible attempt at the real gold SQL, even if it doesn't match exactly?

- [ ] **Step 4: Nothing to commit**

`reports/baseline.md` (already gitignored from Phase 0) and
`reports/baseline_<date>.jsonl` (gitignored by Task 6, Step 6 above) are
both generated artifacts, not source — there is nothing to commit for
this task. The real run itself and the sanity check in Step 3 are this
task's deliverable.

---

## Self-review notes

- **Spec coverage:** Ollama config (§2, Tasks 2 & 4), `schema_index.py` (§3, Task 1), `generate.py` (§3, Task 2), `execute.py` with both safety behaviors (§3, Task 3), `answer.py` (§3, Task 4), `pipeline.py` (§3, Task 5), prompt design (§4, Tasks 2 & 4), eval harness scored on execution accuracy + hallucinated-number rate over all 103 cases with new (not reused) comparison logic (§5, Task 6), `make baseline` target distinct from `make eval` (§5, Task 6), `reports/baseline.md` contents (§6, Task 6-7) — all covered. §7 (out of scope) is respected: no task touches `classify.py`, `guardrails.py`, `consensus.py`, `verify.py`, `audit.py`, the API/UI, or anything under `ledgerql/data/`/`docs/schema.md`/`evals/gold.jsonl`.
- **Type/signature consistency:** `ExecutionResult` (Task 3) fields (`columns`, `rows`, `error`, `truncated`) are consumed identically in Task 4's `_format_result`, Task 5's `pipeline.ask()`, and Task 6's `run()`. `generate_candidates(question, schema_context, n=1, client=None)` (Task 2) is called with matching keyword usage in Task 5. `write_answer(question, result, client=None)` (Task 4) matches its Task 5 call site.
- **Corrected during self-review:** the original draft of Task 6 suggested reusing `evals/validate_gold.py`'s `check_executes` for scoring — fixed per the spec's own explicit note that this needs new comparison logic (`results_match`), since `check_executes` validates a single query's own result shape rather than comparing two independently-executed result sets. Also corrected the `COUNT(*)`-based slow-query idea for Task 3's timeout test after empirically finding DuckDB optimizes pure cross-join counts to be near-instant even at large scale — replaced with a verified `SUM` of a per-row product, at a row count and join width confirmed by direct timing to take ~1.9s. Removed an unnecessary `sys.path.insert` from `evals/run_eval.py` after confirming empirically that `ledgerql` is importable directly (editable-installed via `uv sync`) with no path manipulation. Replaced a hedgy `hasattr`-guarded model-name lookup in `write_reports` with a direct import — the plan should state what to do, not offer the implementer a choice between a fragile version and a "simplify if it feels fragile" escape hatch. Caught that `.gitignore`'s existing `reports/*.md` rule (confirmed via direct `grep`) does not cover the new `reports/*.jsonl` output, added a `.gitignore` update step to Task 6 rather than leaving Task 7 to guess whether to commit a generated per-case dump.
