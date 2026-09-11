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


def _format_value(value: object) -> str:
    # Large numbers rendered as one undelimited digit string (e.g.
    # "391035000000.0") get a digit dropped on restatement -- a real,
    # deterministic failure found in Phase 4's eval run (391035000000 ->
    # 39103500000, identically across 4 separate gold cases at temperature
    # 0.2, seed 42). Confirmed directly against the live model that
    # comma-grouping the digits before showing them ("391,035,000,000.0")
    # eliminates the drop -- reproduced 3/3 with the ungrouped form, fixed
    # 3/3 after grouping, both at multiple seeds. A prompt-instruction-only
    # attempt ("copy digits exactly") was tried first and did not help;
    # this is a formatting fix, not a wording one. verify.py's own
    # extract_numbers() already strips commas before comparing, so this
    # only changes what the model sees, not how grounding is checked.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:,}"


def _format_result(result: ExecutionResult) -> str:
    header = "\t".join(result.columns)
    if not result.rows:
        return f"{header}\n(no rows)"
    body = "\n".join("\t".join(_format_value(v) for v in row) for row in result.rows)
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
