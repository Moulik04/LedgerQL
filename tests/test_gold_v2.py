"""Gold v2 comparator (evals/README.md 6g): entity targets at company level (V2),
ratio scale (V3), tolerance in every mode (V6), strict vs relaxed."""

import json
from pathlib import Path

import duckdb
import pytest

from evals.gold_v2 import (
    GOLD_V1_PATH,
    GOLD_V2_PATH,
    EntityResolver,
    build_gold_v2,
    match,
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


# ---- V2: entity resolution --------------------------------------------------


def test_resolver_finds_cik_ticker_and_name_and_reports_which(resolver):
    assert resolver.resolve(320193) == (320193, "cik")
    assert resolver.resolve("AAPL") == (320193, "ticker")
    assert resolver.resolve("Apple Inc.") == (320193, "name")
    assert resolver.resolve("apple inc.") is None  # exact, no fuzzy matching
    assert resolver.resolve("Apple") is None
    assert resolver.resolve(None) is None
    assert resolver.resolve(True) is None  # a bool is not a cik


def test_entity_column_matches_across_name_ticker_and_cik(resolver):
    c = case(entity_cols=[0])
    gold = [("Apple Inc.",), ("Microsoft",)]
    for pred, via in (
        ([("AAPL",), ("MSFT",)], {"ticker"}),
        ([("Apple Inc.",), ("Microsoft",)], {"name"}),
        ([(320193,), (789019,)], {"cik"}),
    ):
        m = match(c, gold, pred, resolver)
        assert m.matched and m.via == via


def test_entity_column_with_an_unresolvable_cell_does_not_match(resolver):
    c = case(entity_cols=[0])
    assert not match(c, [("Apple Inc.",)], [("Apple",)], resolver).matched


def test_entity_column_with_the_wrong_company_does_not_match(resolver):
    c = case(entity_cols=[0], compare="scalar")
    assert not match(c, [("Apple Inc.",)], [("MSFT",)], resolver).matched


def test_a_column_that_is_not_an_entity_column_is_not_resolved(resolver):
    # The ticker symbol IS the answer here (L12): 'KO' must not match 'Coca-Cola...'.
    c = case(compare="scalar")
    assert match(c, [("KO",)], [("KO",)], resolver).matched
    assert not match(c, [("KO",)], [("Coca-Cola Company (The)",)], resolver).matched


# ---- V3: ratio scale ---------------------------------------------------------


@pytest.mark.parametrize("pred", [17.2086, 0.172086, 1720.86])
def test_ratio_column_matches_fraction_percentage_and_x100_of_percentage(resolver, pred):
    c = case(compare="scalar", ratio_cols=[0], tolerance=0.05)
    assert match(c, [(17.2086,)], [(pred,)], resolver).matched


def test_ratio_column_still_rejects_a_different_quantity(resolver):
    c = case(compare="scalar", ratio_cols=[0], tolerance=0.05)
    assert not match(c, [(17.2086,)], [(0.5,)], resolver).matched
    assert not match(c, [(17.2086,)], [(None,)], resolver).matched


def test_a_non_ratio_column_is_never_rescaled(resolver):
    c = case(compare="scalar", tolerance=0.05)
    assert not match(c, [(17.2086,)], [(0.172086,)], resolver).matched


def test_billions_are_not_a_ratio_rescale(resolver):
    c = case(compare="scalar", tolerance=0.001)
    assert not match(c, [(391.035,)], [(391035000000.0,)], resolver).matched


# ---- V6 and the compare modes --------------------------------------------------


def test_set_and_ordered_use_the_tolerance_v1_ignored(resolver):
    c = case(compare="set", tolerance=1e-6)
    assert match(c, [(1.0000000001, "x")], [(1.0, "x")], resolver).matched
    c = case(compare="ordered", tolerance=1e-6)
    assert match(c, [(1.0000000001,), (2.0,)], [(1.0,), (2.0,)], resolver).matched


def test_ordered_requires_order_and_set_does_not(resolver):
    gold = [("a",), ("b",)]
    assert not match(case(compare="ordered"), gold, [("b",), ("a",)], resolver).matched
    assert match(case(compare="set"), gold, [("b",), ("a",)], resolver).matched


def test_set_collapses_duplicates_like_v1_but_not_missing_rows(resolver):
    assert match(case(compare="set"), [("a",)], [("a",), ("a",)], resolver).matched
    assert not match(case(compare="set"), [("a",), ("b",)], [("a",)], resolver).matched
    assert not match(case(compare="set"), [("a",)], [("a",), ("b",)], resolver).matched


def test_scalar_needs_exactly_one_cell_and_null_matches_null(resolver):
    assert not match(case(compare="scalar"), [(1,)], [(1,), (1,)], resolver).matched
    assert not match(case(compare="scalar"), [(1,)], [(1, 2)], resolver).matched
    assert match(case(compare="scalar_or_null"), [(None,)], [(None,)], resolver).matched
    assert not match(case(compare="scalar_or_null"), [(None,)], [], resolver).matched


def test_empty_and_none_modes_are_unchanged(resolver):
    assert match(case(compare="empty"), [], [], resolver).matched
    assert not match(case(compare="empty"), [], [(1,)], resolver).matched
    assert match(case(compare="none"), [], [(1,)], resolver).matched


def test_strict_rejects_extra_columns_relaxed_accepts_them(resolver):
    c = case(compare="scalar", entity_cols=[0])
    gold = [("Apple Inc.",)]
    pred = [("AAPL", "Apple Inc.", 0.5)]
    assert not match(c, gold, pred, resolver, mode="strict").matched
    assert match(c, gold, pred, resolver, mode="relaxed").matched


def test_relaxed_finds_gold_columns_in_any_position_and_keeps_row_alignment(resolver):
    c = case(compare="ordered", entity_cols=[0])
    gold = [("Apple Inc.", 3.0), ("Microsoft", 2.0)]
    assert match(c, gold, [(3.0, "AAPL", 9), (2.0, "MSFT", 8)], resolver, mode="relaxed").matched
    # values swapped between rows: no column choice aligns them
    assert not match(c, gold, [(2.0, "AAPL"), (3.0, "MSFT")], resolver, mode="relaxed").matched


def test_relaxed_never_accepts_fewer_columns_than_gold(resolver):
    c = case(compare="set")
    assert not match(c, [("a", 1)], [("a",)], resolver, mode="relaxed").matched


# ---- the built gold_v2.jsonl ---------------------------------------------------


def _load(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    return {r["id"]: r for r in rows}


def test_gold_v2_has_the_same_103_ids_and_questions_as_v1():
    v1, v2 = _load(GOLD_V1_PATH), _load(GOLD_V2_PATH)
    assert list(v1) == list(v2) and len(v2) == 103
    assert all(v1[i]["question"] == v2[i]["question"] for i in v1)
    assert all(v1[i]["expected"] == v2[i]["expected"] for i in v1)


def test_committed_gold_v2_is_what_the_builder_produces():
    v1 = list(_load(GOLD_V1_PATH).values())
    assert build_gold_v2(v1) == list(_load(GOLD_V2_PATH).values())


def test_every_changed_case_names_the_rules_it_follows_and_keeps_v1():
    v1, v2 = _load(GOLD_V1_PATH), _load(GOLD_V2_PATH)
    changed = [i for i in v2 if "v2" in v2[i]]
    assert changed  # the audit found seven gold errors, so this cannot be empty
    for i in changed:
        meta = v2[i]["v2"]
        assert meta["rules"] and all(r.startswith("V") for r in meta["rules"])
        assert meta["v1_gold_sql"] == v1[i]["gold_sql"]
        assert meta["v1_compare"] == v1[i]["compare"]
    for i in set(v2) - set(changed):  # unchanged cases are byte-identical to v1 plus empty marks
        assert {k: v2[i][k] for k in v1[i]} == v1[i]
        assert not v2[i].get("entity_cols") and not v2[i].get("ratio_cols")


def test_no_v2_tolerance_exceeds_five_percent():
    assert all(c.get("tolerance", 1e-6) <= 0.05 for c in _load(GOLD_V2_PATH).values())


def test_v1_gold_result_satisfies_v2_gold_under_the_relaxed_rule():
    """v2 only ever drops columns and rescales proportions: v1's own result must
    still contain everything v2 asks for. The named exceptions are the two cases
    where v2 asks for a different computed quantity (R07: a margin that is NULL,
    G05: the difference), so v1's result holds the inputs, not the answer."""
    fixture = require_fixture("tests/fixtures/eval_fixture.duckdb")
    con = duckdb.connect(str(fixture), read_only=True)
    resolver = EntityResolver(con.execute("select cik,ticker,name from companies").fetchall())
    v1, v2 = _load(GOLD_V1_PATH), _load(GOLD_V2_PATH)
    exceptions = {"R07"}
    for i, c in v2.items():
        if c["expected"] not in ("ANSWER", "ANSWER_WITH_ASSUMPTION") or not c.get("gold_sql"):
            continue
        if i in exceptions:
            continue
        r1 = con.execute(v1[i]["gold_sql"]).fetchall()
        r2 = con.execute(c["gold_sql"]).fetchall()
        assert match(c, r2, r1, resolver, mode="relaxed").matched, i
        assert match(c, r2, r2, resolver, mode="strict").matched, i
