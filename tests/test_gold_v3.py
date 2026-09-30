"""Gold v3 comparator (evals/README.md 6i): absolute tolerance, unit scale, pivot equivalence,
alternatives, the built file and its freeze."""

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from evals.gold_v2 import EntityResolver, build_gold_v2, load_v1
from evals.gold_v3 import (
    GOLD_V3_HASH_PATH,
    GOLD_V3_PATH,
    build_gold_v3,
    match_v3,
)
from tests.support import require_fixture

COMPANIES = [
    (320193, "AAPL", "Apple Inc."),
    (789019, "MSFT", "Microsoft"),
    (21344, "KO", "Coca-Cola Company (The)"),
]


@pytest.fixture()
def resolver():
    return EntityResolver(COMPANIES)


def case(**kw):
    base = {"compare": "set", "tolerance": 1e-6, "entity_cols": [], "ratio_cols": []}
    base.update(kw)
    return base


# ---- V5: explicit tolerance type ---------------------------------------------------


@pytest.mark.parametrize("pred,ok", [(94.9, True), (94.2, True), (0.949, True), (0.9461, True),
                                     (48.96, False), (0.4896, False), (96.0, False)])  # fmt: skip
def test_absolute_tolerance_is_percentage_points_after_rescaling_to_gold_units(resolver, pred, ok):
    c = case(compare="scalar", ratio_cols=[0], tolerance=0.5, tolerance_kind="absolute")
    assert match_v3(c, [(94.6,)], [(pred,)], resolver).matched is ok


def test_relative_is_still_the_default_kind(resolver):
    c = case(compare="scalar", tolerance=0.05)
    assert match_v3(c, [(100.0,)], [(104.0,)], resolver).matched
    assert not match_v3(c, [(100.0,)], [(106.0,)], resolver).matched


# ---- V8: unit scale ------------------------------------------------------------------


@pytest.mark.parametrize("pred,ok", [(391.035, True), (391035000000.0, True), (391035.0, False),
                                     (392.0, False)])  # fmt: skip
def test_stated_scale_accepts_the_raw_value_and_no_other_scale(resolver, pred, ok):
    c = case(compare="scalar", tolerance=0.001, scale_cols={"0": 1e9})
    assert match_v3(c, [(391.035,)], [(pred,)], resolver).matched is ok


def test_scale_applies_only_to_its_column(resolver):
    c = case(compare="set", tolerance=0.001, scale_cols={"1": 1e6})
    gold = [("x", 5.0)]
    assert match_v3(c, gold, [("x", 5_000_000.0)], resolver).matched
    assert not match_v3(c, [(5.0, "x")], [(5_000_000.0, "x")], resolver).matched


# ---- V7: pivot equivalence --------------------------------------------------------------

YEARS = case(pivot={"label_cols": [0], "value_col": 1})
GOLD_YEARS = [(2024, 88.0), (2025, 101.0)]


def test_pivot_accepts_long_layout_in_either_column_order(resolver):
    assert match_v3(YEARS, GOLD_YEARS, [(2024, 88.0), (2025, 101.0)], resolver).matched
    assert match_v3(YEARS, GOLD_YEARS, [(101.0, 2025), (88.0, 2024)], resolver).matched


def test_pivot_accepts_a_wide_row_with_label_cells_or_labelled_column_names(resolver):
    assert match_v3(YEARS, GOLD_YEARS, [(2024, 88.0, 2025, 101.0)], resolver).matched
    wide = [(88.0, 101.0)]
    cols = ["net_income_2024", "net_income_2025"]
    assert match_v3(YEARS, GOLD_YEARS, wide, resolver, pred_columns=cols).matched


def test_pivot_rejects_values_under_the_wrong_label(resolver):
    swapped = [(101.0, 88.0)]
    cols = ["net_income_2024", "net_income_2025"]
    assert not match_v3(YEARS, GOLD_YEARS, swapped, resolver, pred_columns=cols).matched
    assert not match_v3(YEARS, GOLD_YEARS, [(2024, 101.0, 2025, 88.0)], resolver).matched


def test_pivot_needs_a_label_from_somewhere(resolver):
    assert not match_v3(YEARS, GOLD_YEARS, [(88.0, 101.0)], resolver).matched
    assert not match_v3(
        YEARS, GOLD_YEARS, [(88.0, 101.0)], resolver, pred_columns=["a", "b"]
    ).matched


def test_pivot_strict_rejects_unexplained_cells_and_relaxed_ignores_them(resolver):
    row = [("MSFT", 88.0, 101.0)]
    cols = ["ticker", "net_income_2024", "net_income_2025"]
    assert not match_v3(YEARS, GOLD_YEARS, row, resolver, pred_columns=cols).matched
    assert match_v3(YEARS, GOLD_YEARS, row, resolver, "relaxed", pred_columns=cols).matched


def test_pivot_with_entity_labels_and_a_ratio_value(resolver):
    c = case(
        pivot={"label_cols": [0], "value_col": 1},
        entity_cols=[0],
        ratio_cols=[1],
        tolerance=0.05,
    )
    gold = [("AAPL", 24.0), ("MSFT", 36.0)]
    assert match_v3(c, gold, [("Apple Inc.", 0.24), ("Microsoft", 0.36)], resolver).matched
    cols = ["apple_net_margin", "microsoft_net_margin"]
    assert match_v3(c, gold, [(0.24, 0.36)], resolver, pred_columns=cols).matched
    assert match_v3(c, gold, [("AAPL", 24.0, "MSFT", 36.0)], resolver).matched
    assert not match_v3(c, gold, [(0.36, 0.24)], resolver, pred_columns=cols).matched
    assert not match_v3(c, gold, [(0.24, 0.36)], resolver, pred_columns=["a", "b"]).matched


def test_non_pivot_cases_never_take_the_pivot_path(resolver):
    c = case(compare="set")  # no pivot key
    assert not match_v3(c, GOLD_YEARS, [(101.0, 2025), (88.0, 2024)], resolver).matched


# ---- V9: alternatives ------------------------------------------------------------------


def test_alternatives_each_have_their_own_shape_and_any_match_counts(resolver):
    c = case(
        compare="scalar_or_null",
        alternatives=[{"compare": "set", "tolerance": 1e-6, "entity_cols": [], "ratio_cols": []}],
    )
    gold = [(None,)]
    alt_rows = [[(58471000000.0, None)]]
    assert match_v3(c, gold, [(None,)], resolver, alt_rows=alt_rows).matched
    assert match_v3(c, gold, [(58471000000.0, None)], resolver, alt_rows=alt_rows).matched
    assert not match_v3(c, gold, [(1.0, None)], resolver, alt_rows=alt_rows).matched


# ---- the built gold_v3.jsonl and the freeze ------------------------------------------------


def _load(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    return {r["id"]: r for r in rows}


def test_committed_gold_v3_is_what_the_builder_produces_and_is_frozen():
    v3 = _load(GOLD_V3_PATH)
    assert build_gold_v3(list(_load("evals/gold_v2.jsonl").values())) == list(v3.values())
    digest = hashlib.sha256(Path(GOLD_V3_PATH).read_bytes()).hexdigest()
    assert digest == Path(GOLD_V3_HASH_PATH).read_text().split()[0], (
        "gold_v3.jsonl is FROZEN. Known issues go on evals/KNOWN_GOLD_ISSUES.md, not into a v4. "
        "If this change is deliberate, say so in DECISIONS.md and update gold_v3.sha256."
    )


def test_gold_v3_keeps_ids_questions_and_expected_and_marks_every_case_v3():
    v2, v3 = _load("evals/gold_v2.jsonl"), _load(GOLD_V3_PATH)
    assert list(v2) == list(v3) and len(v3) == 103
    assert all(v2[i]["question"] == v3[i]["question"] for i in v3)
    assert all(v2[i]["expected"] == v3[i]["expected"] for i in v3)
    assert all(c["gold_version"] == "v3" for c in v3.values())


def test_v3_changes_are_exactly_the_approved_ones():
    v3 = _load(GOLD_V3_PATH)
    changed = {i for i, c in v3.items() if "v3" in c}
    assert changed == {"A10", "C04", "U01", "U05", "U07", "T03", "R06", "U03", "R07"}
    for i in changed:
        assert all(r.startswith("V") for r in v3[i]["v3"]["rules"])
    assert {i for i in v3 if v3[i].get("pivot")} == {"T03", "R06", "U03"}
    assert {i for i in v3 if v3[i].get("scale_cols")} == {"U01", "U05", "U07"}
    assert v3["A10"]["tolerance_kind"] == "absolute" and v3["A10"]["tolerance"] == 0.5
    assert v3["C04"]["tolerance_kind"] == "absolute" and v3["C04"]["tolerance"] == 0.5
    assert len(v3["R07"]["alternatives"]) == 1


def test_tolerance_ceilings_relative_at_most_five_percent_absolute_only_on_proportions():
    for i, c in _load(GOLD_V3_PATH).items():
        tol, kind = c.get("tolerance", 1e-6), c.get("tolerance_kind", "relative")
        if kind == "relative":
            assert tol <= 0.05, i
        else:
            assert kind == "absolute" and c["ratio_cols"] and tol <= 1.0, i


def test_every_v3_case_matches_itself_strictly_and_the_v2_result_relaxed():
    fixture = require_fixture("tests/fixtures/eval_fixture.duckdb")
    con = duckdb.connect(str(fixture), read_only=True)
    resolver = EntityResolver(con.execute("select cik,ticker,name from companies").fetchall())
    v3 = _load(GOLD_V3_PATH)
    v2 = {c["id"]: c for c in build_gold_v2(load_v1())}
    for i, c in v3.items():
        if c["expected"] not in ("ANSWER", "ANSWER_WITH_ASSUMPTION") or not c.get("gold_sql"):
            continue
        rows = con.execute(c["gold_sql"]).fetchall()
        alts = [con.execute(a["gold_sql"]).fetchall() for a in c.get("alternatives", [])]
        assert match_v3(c, rows, rows, resolver, alt_rows=alts).matched, i
        r2 = con.execute(v2[i]["gold_sql"]).fetchall()
        assert match_v3(c, rows, r2, resolver, "relaxed", alt_rows=alts).matched, i
    con.close()
