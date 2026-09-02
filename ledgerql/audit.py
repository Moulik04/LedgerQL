"""Stage 8: audit trail.

Records the prompt, generated SQL, every guardrail decision, execution
result summary, final answer, confidence, reason code (if refused/
abstained), and latency for every request. Nothing is silently dropped.
"""


def record(entry: dict) -> str:
    raise NotImplementedError("Phase 3")
