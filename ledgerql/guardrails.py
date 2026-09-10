"""Stage 4: static guardrails.

Structural, sqlglot-based validation of generated SQL -- the hard
safety backstop, independent of whatever classify.py (Layer 1, a soft
LLM-based prefilter) decided. Checks, in order: parses as SQL at all,
is exactly one SELECT statement, only references allowlisted tables,
only references allowlisted (live-introspected) columns, and has a
bounded row cost (a WHERE clause, a LIMIT, or an aggregate somewhere in
the query -- otherwise it's a "give me every row" pattern and gets
blocked outright, not silently capped, so it reliably produces the
gold set's expected ABSTAIN/COST_LIMIT outcome). The four-value
guardrail-event vocabulary (read_only, single_statement,
schema_allowlist, cost_limit) matches evals/gold.jsonl's own
guardrail_must_fire field exactly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import duckdb
import sqlglot
from sqlglot import exp

DB_PATH = os.environ.get("LEDGERQL_DB_PATH", "data/ledgerql.duckdb")
ROW_LIMIT = int(os.environ.get("LEDGERQL_ROW_LIMIT", "1000"))

ALLOWED_TABLES = {
    "companies",
    "filings",
    "financial_facts",
    "v_revenue",
    "v_net_income",
    "v_total_assets",
    "v_cash",
}


@dataclass
class GuardrailResult:
    ok: bool
    sql: str
    events: list[str] = field(default_factory=list)
    reason_code: str | None = None
    detail: str | None = None


def parse_sql(sql: str) -> list[exp.Expression]:
    return sqlglot.parse(sql, read="duckdb")


def check_single_select(stmts: list[exp.Expression]) -> str | None:
    """Returns the guardrail event name if `stmts` isn't exactly one
    SELECT/UNION statement, else None."""
    if len(stmts) != 1:
        return "single_statement"
    if not isinstance(stmts[0], exp.Select | exp.Union):
        return "read_only"
    return None


def check_table_allowlist(stmt: exp.Expression) -> set[str]:
    """Returns referenced table names not in ALLOWED_TABLES (CTE
    aliases excluded). Empty set means no violation."""
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    tables = {t.name.lower() for t in stmt.find_all(exp.Table)}
    return tables - ALLOWED_TABLES - cte_names


def _live_columns(db_path: str) -> set[str]:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        placeholders = ",".join(f"'{t}'" for t in ALLOWED_TABLES)
        rows = con.execute(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name IN ({placeholders})"
        ).fetchall()
    finally:
        con.close()
    return {r[0].lower() for r in rows}


def _is_unbounded(stmt: exp.Expression) -> bool:
    has_where = bool(list(stmt.find_all(exp.Where)))
    has_limit = bool(list(stmt.find_all(exp.Limit)))
    has_agg = bool(list(stmt.find_all(exp.AggFunc))) or bool(list(stmt.find_all(exp.Group)))
    return not (has_where or has_limit or has_agg)


def validate(sql: str, db_path: str = DB_PATH, row_limit: int = ROW_LIMIT) -> GuardrailResult:
    try:
        stmts = parse_sql(sql)
    except Exception as e:  # noqa: BLE001
        return GuardrailResult(ok=False, sql=sql, reason_code="EXEC_ERROR", detail=str(e))

    event = check_single_select(stmts)
    if event is not None:
        detail = (
            f"{len(stmts)} statements found, expected exactly 1"
            if event == "single_statement"
            else f"top-level statement is {type(stmts[0]).__name__}, not SELECT"
        )
        return GuardrailResult(
            ok=False, sql=sql, events=[event], reason_code="OUT_OF_SCOPE", detail=detail
        )

    stmt = stmts[0]

    stray_tables = check_table_allowlist(stmt)
    if stray_tables:
        return GuardrailResult(
            ok=False,
            sql=sql,
            events=["schema_allowlist"],
            reason_code="SCHEMA_MISMATCH",
            detail=f"references non-allowlisted table(s): {sorted(stray_tables)}",
        )

    allowed_columns = _live_columns(db_path)
    referenced_columns = {c.name.lower() for c in stmt.find_all(exp.Column)}
    stray_columns = referenced_columns - allowed_columns
    if stray_columns:
        return GuardrailResult(
            ok=False,
            sql=sql,
            events=["schema_allowlist"],
            reason_code="SCHEMA_MISMATCH",
            detail=f"references non-allowlisted column(s): {sorted(stray_columns)}",
        )

    if _is_unbounded(stmt):
        return GuardrailResult(
            ok=False,
            sql=sql,
            events=["cost_limit"],
            reason_code="COST_LIMIT",
            detail="query has no WHERE, LIMIT, or aggregate -- would return every row",
        )

    return GuardrailResult(ok=True, sql=stmt.sql(dialect="duckdb", comments=False))
