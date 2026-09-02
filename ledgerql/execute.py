"""Stage 5: execution.

Runs a validated SQL candidate against a read-only DuckDB connection with
a timeout. Never opens a write-capable connection.
"""


def execute(sql: str) -> None:
    raise NotImplementedError("Phase 2")
