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
        load_gold("v4")


def test_v3_cases_use_the_v3_comparator_with_column_names_and_alternatives():
    pivot = {
        "gold_version": "v3", "compare": "set", "pivot": {"label_cols": [0], "value_col": 1},
        "entity_cols": [], "ratio_cols": [],
    }  # fmt: skip
    gold = [(2024, 88.0), (2025, 101.0)]
    wide, cols = [(88.0, 101.0)], ["ni_2024", "ni_2025"]
    assert case_matches(pivot, gold, wide, DB, pred_columns=cols)
    assert not case_matches(pivot, gold, wide, DB)  # no labels without the column names
    alt = {
        "gold_version": "v3", "compare": "scalar_or_null", "entity_cols": [], "ratio_cols": [],
        "alternatives": [{"gold_sql": "SELECT 1 AS a, NULL AS b", "compare": "set"}],
    }  # fmt: skip
    assert case_matches(alt, [(None,)], [(None,)], DB)
    assert case_matches(alt, [(None,)], [(1, None)], DB)  # the alternative's own gold rows


def test_load_gold_v3_marks_every_case_v3():
    assert all(c["gold_version"] == "v3" for c in load_gold("v3").values())


def test_a_heldout_gold_file_is_only_usable_when_it_matches_its_freeze_pin(tmp_path):
    from evals.scoring import FrozenGoldError, require_frozen

    plain = tmp_path / "gold_anything.jsonl"
    plain.write_text("{}\n")
    require_frozen(plain)  # only held-out files are guarded

    held = tmp_path / "heldout_v1.jsonl"
    held.write_text('{"id": "H01"}\n')
    with pytest.raises(FrozenGoldError, match="not frozen"):
        require_frozen(held)  # no pin yet: the set is not frozen, no model may run on it
    import hashlib

    (tmp_path / "heldout_v1.sha256").write_text(
        hashlib.sha256(held.read_bytes()).hexdigest() + "  heldout_v1.jsonl\\n"
    )
    require_frozen(held)
    held.write_text('{"id": "H01", "edited": true}\\n')
    with pytest.raises(FrozenGoldError, match="does not match"):
        require_frozen(held)
