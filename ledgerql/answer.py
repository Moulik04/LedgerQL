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
