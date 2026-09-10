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
