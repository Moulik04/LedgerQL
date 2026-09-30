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

VERSIONS = ("v1", "v2")


def load_gold(version: str = "v1") -> dict[str, dict]:
    if version not in VERSIONS:
        raise ValueError(f"gold version must be one of {VERSIONS}, got {version!r}")
    path = GOLD_V1_PATH if version == "v1" else GOLD_V2_PATH
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["id"]: r for r in rows}


@lru_cache(maxsize=4)
def resolver_for(db_path: str) -> EntityResolver:
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        return EntityResolver.from_connection(con)
    finally:
        con.close()


def case_match(
    case: dict, gold_rows: list, pred_rows: list, db_path: str, mode: str = "strict"
) -> Match:
    """v1 cases: `results_match` (mode is ignored, v1 has one comparator). v2 cases:
    `gold_v2.match` in `mode` ("strict" is the headline, "relaxed" the second figure)."""
    # Imported here: run_eval imports this module for its own scoring.
    from evals.run_eval import results_match

    if case.get("gold_version") == "v2":
        return match_v2(case, gold_rows, pred_rows, resolver_for(str(db_path)), mode=mode)
    return Match(results_match(gold_rows, pred_rows, case["compare"], case.get("tolerance", 1e-6)))


def case_matches(
    case: dict, gold_rows: list, pred_rows: list, db_path: str, mode: str = "strict"
) -> bool:
    return case_match(case, gold_rows, pred_rows, db_path, mode).matched
