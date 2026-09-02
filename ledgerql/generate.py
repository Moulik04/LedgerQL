"""Stage 3: SQL generation.

Calls the local Ollama model (default qwen2.5-coder:7b) for N candidate
SQL queries at temperature > 0, given the question and retrieved schema.
"""


def generate_candidates(question: str, schema_context: str, n: int = 5) -> list[str]:
    raise NotImplementedError("Phase 2")
