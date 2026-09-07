import pytest

from evals.run_eval import extract_numbers, results_match


def test_extract_numbers_handles_plain_integer():
    assert extract_numbers("The value is 391035000000.") == [391035000000.0]


def test_extract_numbers_handles_billions_word():
    assert extract_numbers("Revenue was $391.0 billion.") == [391000000000.0]


def test_extract_numbers_handles_percent():
    numbers = extract_numbers("Growth was 6.43%.")
    assert numbers == [6.43]


def test_extract_numbers_excludes_plausible_years():
    # A bare 4-digit number in the 2000-2099 range reads as a fiscal
    # year, not a data value, and must not be treated as an ungrounded
    # numeric claim.
    numbers = extract_numbers("This is fiscal year 2024 data.")
    assert numbers == []


def test_extract_numbers_handles_multiple_values():
    numbers = extract_numbers("Revenue was $391.0 billion and net income was $93.7 billion.")
    assert numbers == [391000000000.0, 93700000000.0]


def test_results_match_scalar_within_tolerance():
    assert results_match([(391035000000.0,)], [(391035000000.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(391035000001.0,)], "scalar") is True
    assert results_match([(391035000000.0,)], [(1.0,)], "scalar") is False


def test_results_match_scalar_respects_custom_tolerance():
    assert results_match([(100.0,)], [(105.0,)], "scalar", tolerance=0.05) is True
    assert results_match([(100.0,)], [(106.0,)], "scalar", tolerance=0.05) is False


def test_results_match_empty():
    assert results_match([], [], "empty") is True
    assert results_match([], [(1,)], "empty") is False


def test_results_match_set_ignores_order():
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], "set") is True
    assert results_match([(1, "a")], [(2, "b")], "set") is False


def test_results_match_ordered_requires_same_order():
    assert results_match([(1,), (2,)], [(1,), (2,)], "ordered") is True
    assert results_match([(1,), (2,)], [(2,), (1,)], "ordered") is False


def test_results_match_scalar_or_null_treats_both_none_as_match():
    assert results_match([(None,)], [(None,)], "scalar_or_null") is True
    assert results_match([(None,)], [(5.0,)], "scalar_or_null") is False


def test_results_match_raises_on_unknown_compare_value():
    with pytest.raises(ValueError, match="unknown compare value"):
        results_match([(1,)], [(1,)], "not_a_real_compare_type")
