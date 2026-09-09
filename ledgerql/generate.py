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
