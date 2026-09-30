# ruff: noqa: E501  (the per-case SQL strings are single literals so they read as gold)
"""Gold v3: the last edition of the 103 cases, and its comparator.

Rules: evals/README.md section 6i, committed before this file existed. v3 keeps v2's V1-V4
and V6 (evals/gold_v2.py) and adds:

- V5, revised: `tolerance_kind` is `relative` (default) or `absolute`; absolute is for
  proportion columns only (`A10`, `C04`: 0.5 percentage points).
- V7 pivot equivalence: `pivot` cases are compared as sets of (label, value) pairs, wide or long.
- V8 unit-scale equivalence: `scale_cols` {column: factor}; raw or scaled both match.
- V9 alternatives: `alternatives` lists further accepted shapes; any match counts.

    python -m evals.gold_v3            # write evals/gold_v3.jsonl from gold_v2.jsonl
    python -m evals.gold_v3 --freeze   # also pin it (evals/gold_v3.sha256), once
    python -m evals.gold_v3 --check    # exit 1 if the file differs from the builder or the pin

Once frozen the 103 cases do not change. Issues go on evals/KNOWN_GOLD_ISSUES.md, not into a v4.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from pathlib import Path

from evals.gold_v2 import (
    DEFAULT_TOLERANCE,
    MAX_RELAXED_COLUMNS,
    RATIO_FACTORS,
    EntityResolver,
    Match,
    _is_number,
)
from ledgerql.entity_link import same_company

GOLD_V2_PATH = Path(__file__).resolve().parent / "gold_v2.jsonl"
GOLD_V3_PATH = Path(__file__).resolve().parent / "gold_v3.jsonl"
GOLD_V3_HASH_PATH = Path(__file__).resolve().parent / "gold_v3.sha256"

_NO = Match(False)
_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")


# --------------------------------------------------------------------------
# Comparator
# --------------------------------------------------------------------------


def _near(gold, pred, tol: float, kind: str) -> bool:
    g, p = float(gold), float(pred)
    if kind == "absolute":
        return abs(p - g) <= tol + 1e-12
    return abs(p - g) <= max(abs(g) * tol, 1e-9)


def _kinds(case: dict, width: int) -> list[tuple[str, float | None]]:
    entity = set(case.get("entity_cols") or [])
    ratio = set(case.get("ratio_cols") or [])
    scale = {int(k): v for k, v in (case.get("scale_cols") or {}).items()}
    out: list[tuple[str, float | None]] = []
    for j in range(width):
        if j in entity:
            out.append(("entity", None))
        elif j in ratio:
            out.append(("ratio", None))
        elif j in scale:
            out.append(("scale", scale[j]))
        else:
            out.append(("plain", None))
    return out


def _cell(kind, factor, gold, pred, tol, tkind, resolver, via) -> bool:
    if kind == "entity":
        g = resolver.resolve(gold)
        if g is None:
            raise ValueError(f"gold entity cell {gold!r} does not resolve to a company")
        p = resolver.resolve(pred)
        if p is None or p[0] != g[0]:
            return False
        via.add(p[1])
        return True
    if gold is None or pred is None:
        return gold is None and pred is None
    if _is_number(gold) and _is_number(pred):
        if kind == "ratio":
            return any(_near(gold, float(pred) * f, tol, tkind) for f in RATIO_FACTORS)
        if kind == "scale":
            return _near(gold, pred, tol, tkind) or _near(float(gold) * factor, pred, tol, tkind)
        return _near(gold, pred, tol, tkind)
    return gold == pred


def _row(kinds, grow, prow, tol, tkind, resolver, via) -> bool:
    if len(grow) != len(prow):
        return False
    return all(
        _cell(k, f, g, p, tol, tkind, resolver, via)
        for (k, f), g, p in zip(kinds, grow, prow, strict=True)
    )


def _strict(case, gold_rows, pred_rows, resolver) -> Match:
    compare = case["compare"]
    tol = case.get("tolerance", DEFAULT_TOLERANCE)
    tkind = case.get("tolerance_kind", "relative")
    via: set = set()
    if compare in ("scalar", "count", "scalar_or_null"):
        if len(pred_rows) != 1 or len(pred_rows[0]) != 1:
            return _NO
        grow = tuple(gold_rows[0][:1]) if gold_rows else (None,)
        ok = _row(_kinds(case, 1), grow, tuple(pred_rows[0]), tol, tkind, resolver, via)
        return Match(ok, frozenset(via)) if ok else _NO
    if not gold_rows:
        return Match(not pred_rows)
    kinds = _kinds(case, len(gold_rows[0]))
    if compare == "ordered":
        if len(gold_rows) != len(pred_rows):
            return _NO
        ok = all(
            _row(kinds, g, p, tol, tkind, resolver, via)
            for g, p in zip(gold_rows, pred_rows, strict=True)
        )
        return Match(ok, frozenset(via)) if ok else _NO
    if compare == "set":
        for g in gold_rows:
            if not any(_row(kinds, g, p, tol, tkind, resolver, set()) for p in pred_rows):
                return _NO
        for p in pred_rows:
            if not any(_row(kinds, g, p, tol, tkind, resolver, via) for g in gold_rows):
                return _NO
        return Match(True, frozenset(via))
    raise ValueError(f"unknown compare value: {compare!r}")


# ---- V7: pivot ------------------------------------------------------------------------


def _company_of(resolver: EntityResolver, cik: int) -> tuple[str | None, str | None]:
    rev = getattr(resolver, "_reverse", None)
    if rev is None:
        rev = {}
        for ticker, c in resolver._tickers.items():
            rev.setdefault(c, [None, None])[0] = ticker
        for name, c in resolver._names.items():
            rev.setdefault(c, [None, None])[1] = name
        resolver._reverse = rev
    ticker, name = rev.get(cik, (None, None))
    return ticker, name


def _label_eq(entity: bool, gold_label, cell, resolver) -> bool:
    if isinstance(cell, bool) or cell is None:
        return False
    if entity:
        g, p = resolver.resolve(gold_label), resolver.resolve(cell)
        return g is not None and p is not None and g[0] == p[0]
    return cell == gold_label and type(cell) is not float


def _header_has(entity: bool, gold_label, header: str, resolver) -> bool:
    if not entity:
        return str(gold_label) in _YEAR.findall(header)
    g = resolver.resolve(gold_label)
    if g is None:
        return False
    ticker, name = _company_of(resolver, g[0])
    words = {w.lower() for w in re.split(r"[^A-Za-z0-9]+", header) if w}
    if ticker and len(ticker) >= 2 and ticker.lower() in words:
        return True
    return bool(name) and same_company(header.replace("_", " "), name)


def _pivot(case, gold_rows, pred_rows, pred_columns, resolver, mode) -> Match:
    spec = case["pivot"]
    if len(spec["label_cols"]) != 1:
        raise NotImplementedError("pivot supports one label column")
    lcol, vcol = spec["label_cols"][0], spec["value_col"]
    entity = lcol in set(case.get("entity_cols") or [])
    kind, factor = _kinds(case, len(gold_rows[0]))[vcol]
    tol = case.get("tolerance", DEFAULT_TOLERANCE)
    tkind = case.get("tolerance_kind", "relative")
    glabels = [g[lcol] for g in gold_rows]

    def gold_label(cell):
        return next((gl for gl in glabels if _label_eq(entity, gl, cell, resolver)), None)

    def header_label(name):
        hits = [gl for gl in glabels if _header_has(entity, gl, name, resolver)]
        return hits[0] if len(hits) == 1 else None

    pairs: list[tuple] = []
    unexplained = 0
    for row in pred_rows:
        used = [False] * len(row)
        is_label = [gold_label(c) is not None for c in row]
        for j, cell in enumerate(row):
            if is_label[j] or not _is_number(cell):
                continue
            lab = None
            if j > 0 and is_label[j - 1] and not used[j - 1]:
                lab, used[j - 1] = gold_label(row[j - 1]), True
            elif j + 1 < len(row) and is_label[j + 1] and not used[j + 1]:
                lab, used[j + 1] = gold_label(row[j + 1]), True
            elif pred_columns is not None and j < len(pred_columns):
                lab = header_label(pred_columns[j])
            if lab is not None:
                pairs.append((lab, cell))
                used[j] = True
        unexplained += used.count(False)
    if mode == "strict" and unexplained:
        return _NO
    via: set = set()

    def same(gp, pp):
        return _label_eq(entity, gp[0], pp[0], resolver) and _cell(
            kind, factor, gp[1], pp[1], tol, tkind, resolver, via
        )

    gold_pairs = [(g[lcol], g[vcol]) for g in gold_rows]
    if not pairs or not all(any(same(g, p) for p in pairs) for g in gold_pairs):
        return _NO
    if not all(any(same(g, p) for g in gold_pairs) for p in pairs):
        return _NO
    return Match(True, frozenset(via))


# ---- top level ---------------------------------------------------------------------------


def _match_one(case, gold_rows, pred_rows, resolver, mode, pred_columns) -> Match:
    compare = case["compare"]
    if compare == "none":
        return Match(True)
    if compare == "empty":
        return Match(len(pred_rows) == 0)
    if mode == "strict":
        m = _strict(case, gold_rows, pred_rows, resolver)
    else:
        m = _relaxed(case, gold_rows, pred_rows, resolver)
    if m.matched or not case.get("pivot") or not gold_rows or not pred_rows:
        return m
    return _pivot(case, gold_rows, pred_rows, pred_columns, resolver, mode)


def _relaxed(case, gold_rows, pred_rows, resolver) -> Match:
    width = len(gold_rows[0]) if gold_rows else 1
    if not pred_rows:
        return _strict(case, gold_rows, pred_rows, resolver)
    n = len(pred_rows[0])
    if n < width or n > MAX_RELAXED_COLUMNS:
        return _NO
    for cols in itertools.permutations(range(n), width):
        projected = [tuple(row[c] for c in cols) for row in pred_rows]
        m = _strict(case, gold_rows, projected, resolver)
        if m.matched:
            return m
    return _NO


def match_v3(
    case: dict,
    gold_rows: list,
    pred_rows: list,
    resolver: EntityResolver,
    mode: str = "strict",
    pred_columns: list[str] | None = None,
    alt_rows: list[list] | None = None,
) -> Match:
    """Does `pred_rows` answer `case` under v3? `alt_rows` are the gold rows of each of
    `case["alternatives"]`, in order; a match against any accepted shape counts."""
    if mode not in ("strict", "relaxed"):
        raise ValueError(f"unknown mode: {mode!r}")
    alternatives = case.get("alternatives") or []
    if alternatives and (alt_rows is None or len(alt_rows) != len(alternatives)):
        raise ValueError("a case with alternatives needs the gold rows of each alternative")
    gold = [tuple(r) for r in gold_rows]
    pred = [tuple(r) for r in pred_rows]
    variants = [(case, gold)] + [
        (alt, [tuple(r) for r in rows])
        for alt, rows in zip(alternatives, alt_rows or [], strict=True)
    ]
    for variant, rows in variants:
        m = _match_one(variant, rows, pred, resolver, mode, pred_columns)
        if m.matched:
            return m
    return _NO


# --------------------------------------------------------------------------
# The conversion table: v2 -> v3
# --------------------------------------------------------------------------

_R07_ORIGINAL = (
    "SELECT n.value AS net_income, r.value AS revenue FROM v_net_income n LEFT JOIN v_revenue r "
    "ON r.cik=n.cik AND r.fiscal_year=n.fiscal_year WHERE n.ticker='JPM' AND n.fiscal_year=2024"
)

CHANGES: dict[str, dict] = {
    # V5 (revised): 0.5 meant percentage points.
    "A10": {"tolerance": 0.5, "tolerance_kind": "absolute", "rules": ["V5"]},
    "C04": {"tolerance": 0.5, "tolerance_kind": "absolute", "rules": ["V5"]},
    # V8: the question states a scale.
    "U01": {"scale_cols": {"0": 1e9}, "rules": ["V8"]},
    "U05": {"scale_cols": {"0": 1e9}, "rules": ["V8"]},
    "U07": {"scale_cols": {"0": 1e6}, "rules": ["V8"]},
    # V7: one quantity for several named periods or entities.
    "T03": {"pivot": {"label_cols": [0], "value_col": 1}, "rules": ["V7"]},
    "R06": {"pivot": {"label_cols": [0], "value_col": 1}, "rules": ["V7"]},
    "U03": {"pivot": {"label_cols": [0], "value_col": 1}, "rules": ["V7"]},
    # V9: "not computable" has two accepted shapes.
    "R07": {
        "alternatives": [
            {
                "gold_sql": _R07_ORIGINAL,
                "compare": "set",
                "tolerance": 1e-6,
                "entity_cols": [],
                "ratio_cols": [],
            }
        ],
        "rules": ["V9"],
    },
}


def build_gold_v3(v2_cases: list[dict]) -> list[dict]:
    """v2 cases with `CHANGES` applied and every case marked v3."""
    unknown = set(CHANGES) - {c["id"] for c in v2_cases}
    if unknown:
        raise ValueError(f"CHANGES names cases that are not in gold: {sorted(unknown)}")
    out = []
    for case in v2_cases:
        change = CHANGES.get(case["id"])
        new = {**case, "gold_version": "v3"}
        if change is not None:
            meta = {"rules": change["rules"]}
            for key in ("tolerance", "tolerance_kind"):
                if key in change:
                    meta[f"v2_{key}"] = case.get(key)
            for key, value in change.items():
                if key != "rules":
                    new[key] = value
            new["v3"] = meta
        out.append(new)
    return out


def load_v2() -> list[dict]:
    return [json.loads(line) for line in GOLD_V2_PATH.read_text().splitlines() if line.strip()]


def render(cases: list[dict]) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)


def digest(path: Path = GOLD_V3_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args(argv)
    text = render(build_gold_v3(load_v2()))
    if args.check:
        same = GOLD_V3_PATH.exists() and GOLD_V3_PATH.read_text() == text
        pinned = GOLD_V3_HASH_PATH.exists() and GOLD_V3_HASH_PATH.read_text().split()[0] == digest()
        print(f"matches builder: {same}; matches the freeze pin: {pinned}")
        return 0 if same and pinned else 1
    if GOLD_V3_HASH_PATH.exists() and GOLD_V3_PATH.read_text() != text:
        print("gold_v3.jsonl is FROZEN and the builder would change it; refusing.", file=sys.stderr)
        return 2
    GOLD_V3_PATH.write_text(text)
    print(f"wrote {GOLD_V3_PATH} ({len(CHANGES)} cases changed of {text.count(chr(10))})")
    if args.freeze:
        if GOLD_V3_HASH_PATH.exists():
            print("already frozen", file=sys.stderr)
            return 2
        GOLD_V3_HASH_PATH.write_text(f"{digest()}  gold_v3.jsonl\n")
        print(f"froze: {digest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
