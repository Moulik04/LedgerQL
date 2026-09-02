"""Stage 7a: grounded answer generation.

Writes the natural-language answer using only the winning result table —
the model is never shown the raw question again at this stage, only the
data it must summarize.
"""


def write_answer(question: str, result_table) -> str:
    raise NotImplementedError("Phase 4")
