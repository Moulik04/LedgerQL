"""Stage 7b: numeric verifier.

Checks every number in the generated answer appears in the result set,
plus unit and fiscal-period consistency. Any unsupported number forces
an ABSTAIN.
"""


def verify(answer: str, result_table) -> bool:
    raise NotImplementedError("Phase 4")
