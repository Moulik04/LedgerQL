"""Orchestrates stages 1-8 end to end and returns the API response.

See LEDGERQL_MASTER_PROMPT.md section 5 (Architecture) for the full
question -> refusal/answer flow this module wires together.
"""


def ask(question: str) -> dict:
    raise NotImplementedError("Phase 2")
