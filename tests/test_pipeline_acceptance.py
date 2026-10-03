from evals import pipeline_acceptance as P


def test_the_confusion_matrix_is_expected_by_observed_over_all_three_states():
    cases = [{"expected": "ANSWER", "state": "ANSWER"}, {"expected": "ANSWER", "state": "ABSTAIN"},
             {"expected": "ANSWER_WITH_ASSUMPTION", "state": "ANSWER_WITH_ASSUMPTION"},
             {"expected": "ABSTAIN", "state": "ANSWER_WITH_ASSUMPTION"}]  # fmt: skip
    m = P.confusion(cases)
    assert m["ANSWER"]["ANSWER"] == 1 and m["ANSWER"]["ABSTAIN"] == 1
    assert m["ABSTAIN"]["ANSWER_WITH_ASSUMPTION"] == 1
    assert m["ANSWER_WITH_ASSUMPTION"]["ANSWER_WITH_ASSUMPTION"] == 1
    assert sum(sum(row.values()) for row in m.values()) == 4


def test_headline_rates_are_wrong_over_answered_and_answered_over_answerable():
    cases = [
        {"expected": "ANSWER", "state": "ANSWER", "correct_v3": True},
        {"expected": "ANSWER", "state": "ANSWER", "correct_v3": False},
        {"expected": "ANSWER_WITH_ASSUMPTION", "state": "ABSTAIN", "correct_v3": False},
        {"expected": "ABSTAIN", "state": "ABSTAIN", "correct_v3": None},
    ]
    h = P.headline(cases)
    assert h["confidently_wrong"] == {"wrong": 1, "answered": 2}
    assert h["coverage"] == {"answered": 2, "answerable": 3}


def test_infra_failed_cases_are_excluded_from_a_partial_runs_figures_and_named():
    records = [{"id": "A", "execution_error": "[Errno 111] Connection refused"},
               {"id": "B", "execution_error": None}]  # fmt: skip
    kept, dropped = P.split_usable(records)
    assert [r["id"] for r in kept] == ["B"] and dropped == ["A"]
