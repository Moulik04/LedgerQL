import pytest

from evals.gold_v2 import Match
from evals.scoring import case_match, case_matches, load_gold, resolver_for

DB = "tests/fixtures/eval_fixture.duckdb"


def test_v1_cases_use_the_v1_comparator_unchanged():
    case = {"compare": "scalar", "tolerance": 0.05}
    assert case_matches(case, [(100.0,)], [(104.0,)], DB)
    assert not case_matches(case, [(100.0,)], [(1.04,)], DB)  # v1 has no ratio rescale
    assert case_match(case, [(1,)], [(1,)], DB) == Match(True)


def test_v2_cases_use_the_v2_comparator():
    case = {
        "gold_version": "v2",
        "compare": "scalar",
        "tolerance": 0.05,
        "ratio_cols": [0],
        "entity_cols": [],
    }
    assert case_matches(case, [(100.0,)], [(1.04,)], DB)


def test_v2_entity_resolution_uses_the_given_database():
    case = {"gold_version": "v2", "compare": "scalar", "entity_cols": [0], "ratio_cols": []}
    m = case_match(case, [("Apple Inc.",)], [("AAPL",)], DB)
    assert m.matched and m.via == {"ticker"}
    assert resolver_for(DB) is resolver_for(DB)  # built once per database


def test_load_gold_marks_only_v2_cases_and_rejects_unknown_versions():
    v1, v2 = load_gold("v1"), load_gold("v2")
    assert not any("gold_version" in c for c in v1.values())
    assert all(c["gold_version"] == "v2" for c in v2.values())
    with pytest.raises(ValueError):
        load_gold("v3")
