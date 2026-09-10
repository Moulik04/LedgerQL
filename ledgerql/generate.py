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
