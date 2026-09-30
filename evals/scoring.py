"""One entry point for "does this result answer this case", for either gold version.

A case loaded from `gold_v2.jsonl` carries `gold_version: "v2"` and is compared by
`evals.gold_v2.match` (evals/README.md 6g). Every other case is compared by v1's
`run_eval.results_match`, unchanged, so a v1 figure computed through here is
identical to one computed before v2 existed.
"""

from __future__ import annotations

import json
from functools import lru_cache

import duckdb

from evals.gold_v2 import GOLD_V1_PATH, GOLD_V2_PATH, EntityResolver, Match
from evals.gold_v2 import match as match_v2
from evals.gold_v3 import GOLD_V3_PATH, match_v3

VERSIONS = ("v1", "v2", "v3")


class FrozenGoldError(RuntimeError):
    """A held-out gold file was used before it was frozen, or after it was edited."""


def require_frozen(path) -> None:
    """Refuse a held-out gold file (`heldout*.jsonl`) unless a sibling `.sha256` pins exactly its
    bytes (evals/HELDOUT_PROTOCOL.md section 5: no model runs on the set until it is frozen).
    Any other gold file is not guarded here."""
    import hashlib
    from pathlib import Path

    path = Path(path)
    if not path.name.startswith("heldout"):
        return
    pin = path.with_suffix(".sha256")
    if not pin.exists():
        raise FrozenGoldError(f"{path.name} is not frozen: no {pin.name}; no model may run on it")
    if pin.read_text().split()[0] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise FrozenGoldError(
            f"{path.name} does not match {pin.name}: it was edited after the freeze"
        )


def load_gold(version: str = "v1") -> dict[str, dict]:
    if version not in VERSIONS:
        raise ValueError(f"gold version must be one of {VERSIONS}, got {version!r}")
    path = {"v1": GOLD_V1_PATH, "v2": GOLD_V2_PATH, "v3": GOLD_V3_PATH}[version]
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["id"]: r for r in rows}


@lru_cache(maxsize=4)
def resolver_for(db_path: str) -> EntityResolver:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        return EntityResolver.from_connection(con)
    finally:
        con.close()


@lru_cache(maxsize=64)
def _alternative_rows(db_path: str, sql: str) -> tuple:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        return tuple(tuple(r) for r in con.execute(sql).fetchall())
    finally:
        con.close()


def case_match(
    case: dict,
    gold_rows: list,
    pred_rows: list,
    db_path: str,
    mode: str = "strict",
    pred_columns: list[str] | None = None,
) -> Match:
    """v1 cases: `results_match` (mode is ignored, v1 has one comparator). v2 and v3 cases:
    `gold_v2.match` / `gold_v3.match_v3` in `mode` ("strict" is the headline, "relaxed" the
    second figure). `pred_columns` (the candidate's column names) only matters to v3's pivot
    rule, which can read a label from a column name."""
    # Imported here: run_eval imports this module for its own scoring.
    from evals.run_eval import results_match

    version = case.get("gold_version")
    if version == "v3":
        alts = [
            list(_alternative_rows(str(db_path), a["gold_sql"]))
            for a in case.get("alternatives", [])
        ]
        return match_v3(
            case,
            gold_rows,
            pred_rows,
            resolver_for(str(db_path)),
            mode=mode,
            pred_columns=pred_columns,
            alt_rows=alts,
        )
    if version == "v2":
        return match_v2(case, gold_rows, pred_rows, resolver_for(str(db_path)), mode=mode)
    return Match(results_match(gold_rows, pred_rows, case["compare"], case.get("tolerance", 1e-6)))


def case_matches(
    case: dict,
    gold_rows: list,
    pred_rows: list,
    db_path: str,
    mode: str = "strict",
    pred_columns: list[str] | None = None,
) -> bool:
    return case_match(case, gold_rows, pred_rows, db_path, mode, pred_columns).matched
