"""Read-only lookups of labels (fiscal year, period end date, form names, units) from the database.

Shared by the refusal explanations (`ledgerql/refusal.py`) and the answer framing
(`ledgerql/frame.py`). These return metadata that labels a result, never a financial value, and a
missing or unreadable database returns nothing rather than failing the request.
"""

from __future__ import annotations

import os


def connect(db_path: str | None):
    import duckdb

    path = db_path or os.environ.get("LEDGERQL_DB_PATH", "data/ledgerql.duckdb")
    return duckdb.connect(path, read_only=True, config={"enable_external_access": "false"})


def data(db_path: str | None, sql: str, params: list | None = None) -> list[tuple]:
    try:
        con = connect(db_path)
    except Exception:  # noqa: BLE001 - no database: no label, not an error
        return []
    try:
        return con.execute(sql, params or []).fetchall()
    except Exception:  # noqa: BLE001
        return []
    finally:
        con.close()
