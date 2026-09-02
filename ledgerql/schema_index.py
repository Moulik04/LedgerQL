"""Stage 2: schema retrieval.

Picks the relevant tables/columns and few-shot examples for a question,
built from docs/schema.md, so the generation prompt stays small and accurate.
"""


def retrieve_schema(question: str) -> None:
    raise NotImplementedError("Phase 2")
