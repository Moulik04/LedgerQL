from evals.confidently_wrong import compute_confidently_wrong_rate, is_confidently_wrong


def test_abstained_record_is_never_confidently_wrong():
    assert is_confidently_wrong({"answer": None}, expected="ANSWER") is False
    assert is_confidently_wrong({"answer": None}, expected="ABSTAIN") is False


def test_answer_expected_record_is_wrong_iff_execution_correct_is_not_true():
    assert is_confidently_wrong({"answer": "x", "execution_correct": True}, "ANSWER") is False
    assert is_confidently_wrong({"answer": "x", "execution_correct": False}, "ANSWER") is True
    # missing execution_correct entirely (e.g. a pipeline-crash record) is
    # not-True, and must count as wrong rather than being silently skipped.
    assert is_confidently_wrong({"answer": "x"}, "ANSWER") is True
    assert (
        is_confidently_wrong({"answer": "x", "execution_correct": True}, "ANSWER_WITH_ASSUMPTION")
        is False
    )
    assert (
        is_confidently_wrong({"answer": "x", "execution_correct": False}, "ANSWER_WITH_ASSUMPTION")
        is True
    )


def test_abstain_expected_record_that_answered_anyway_is_always_wrong():
    # There is no gold_sql to compare against on an ABSTAIN case -- any
    # answer at all is wrong by definition, since refusing was required.
    assert is_confidently_wrong({"answer": "x"}, "ABSTAIN") is True


CASES = {
    "A1": {"id": "A1", "tier": "lookup", "expected": "ANSWER"},
    "A2": {"id": "A2", "tier": "lookup", "expected": "ANSWER"},
    "A3": {"id": "A3", "tier": "aggregation", "expected": "ANSWER"},
    "X1": {"id": "X1", "tier": "adversarial", "expected": "ABSTAIN"},
}


def test_compute_confidently_wrong_rate_overall_and_by_tier():
    per_case = [
        {"id": "A1", "answer": "x", "execution_correct": True},  # right
        {"id": "A2", "answer": "x", "execution_correct": False},  # wrong, same tier
        {"id": "A3", "answer": "x", "execution_correct": False},  # wrong, other tier
        {"id": "X1", "answer": None},  # correctly abstained
    ]
    stats = compute_confidently_wrong_rate(per_case, CASES)
    assert stats["confidently_wrong_count"] == 2
    assert stats["confidently_wrong_rate"] == 2 / 3  # 2 of 3 ANSWERED cases
    assert stats["confidently_wrong_by_tier"] == {"lookup": 1 / 2, "aggregation": 1 / 1}


def test_compute_confidently_wrong_rate_handles_zero_answered_cases():
    per_case = [{"id": "X1", "answer": None}]
    stats = compute_confidently_wrong_rate(per_case, CASES)
    assert stats["confidently_wrong_count"] == 0
    assert stats["confidently_wrong_rate"] == 0.0
    assert stats["confidently_wrong_by_tier"] == {}
