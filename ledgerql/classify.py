"""Stage 1: intent & scope classifier.

Decides whether a question is in-scope for the analyst schema before any
SQL is generated. Out-of-scope or unsafe questions are refused here and
logged, never passed downstream.
"""


def classify(question: str) -> None:
    raise NotImplementedError("Phase 2")
