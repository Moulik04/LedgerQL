"""Stage 4: static guardrails.

Parses each SQL candidate with sqlglot and enforces, at the AST level:
exactly one SELECT statement, no DDL/DML, no comments, no multiple
statements, every table/column exists in the live schema, an enforced
LIMIT, a cost/row estimate cap, and DuckDB dialect compliance.
"""


def validate(sql: str) -> None:
    raise NotImplementedError("Phase 3")
