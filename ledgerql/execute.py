"""Stage 5: execution.

Runs a SQL statement against a read-only DuckDB connection with a
timeout and a row-count cap. This is baseline infrastructure hygiene,
not a guardrail: Phase 2 has no AST validation, no cost estimation, no
schema allowlisting (those are Phase 3's guardrails.py) -- but the
connection is read-only from day one, consistent with the master
prompt's non-negotiable constraint #3, and results are capped so a
pathological query can't exhaust memory or blow the answer-generation
prompt's context.
"""

import concurrent.futures
import os
from dataclasses import dataclass, field

import duckdb

DB_PATH = os.environ.get("LEDGERQL_DB_PATH", "data/ledgerql.duckdb")
ROW_LIMIT = int(os.environ.get("LEDGERQL_ROW_LIMIT", "1000"))
QUERY_TIMEOUT_SECONDS = float(os.environ.get("LEDGERQL_QUERY_TIMEOUT_SECONDS", "10"))


@dataclass
class ExecutionResult:
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False


def execute(
    sql: str,
    db_path: str = DB_PATH,
    timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
    row_limit: int = ROW_LIMIT,
) -> ExecutionResult:
    try:
        con = duckdb.connect(db_path, read_only=True)
    except Exception as e:  # noqa: BLE001
        return ExecutionResult(error=str(e))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(con.execute, sql)
            try:
                cursor = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                con.interrupt()
                return ExecutionResult(error=f"query timed out after {timeout_seconds}s")
            except Exception as e:  # noqa: BLE001
                return ExecutionResult(error=str(e))

            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

        truncated = len(rows) > row_limit
        if truncated:
            rows = rows[:row_limit]
        return ExecutionResult(columns=columns, rows=rows, truncated=truncated)
    except Exception as e:  # noqa: BLE001
        return ExecutionResult(error=str(e))
    finally:
        con.close()
