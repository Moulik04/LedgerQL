import json

from evals.diagnose_abstains import categorize_abstains, format_report


def _gold(case_id, expected, reason_code=None):
    return {"id": case_id, "expected": expected, "reason_code": reason_code}


def _record(case_id, answer, reason_code=None):
    return {"id": case_id, "answer": answer, "reason_code": reason_code}


def test_correct_abstain_matches_gold_reason_code_exactly():
    gold = {"A": _gold("A", "ABSTAIN", "OUT_OF_SCOPE")}
    records = [_record("A", None, "OUT_OF_SCOPE")]

    result = categorize_abstains(records, gold)

    assert result["correct"] == ["A"]
    assert result["structurally_unreachable"] == []
    assert result["reachable_miss"] == []
    assert result["shouldnt_have_abstained"] == {}
    assert result["missed_abstain"] == []


def test_structurally_unreachable_when_gold_reason_code_has_no_pipeline_equivalent():
    # AMBIGUOUS/NO_DATA only exist in the deferred full calibration
    # framework -- the Core-only pipeline can never produce them.
    gold = {"A": _gold("A", "ABSTAIN", "AMBIGUOUS")}
    records = [_record("A", None, "LOW_AGREEMENT")]

    result = categorize_abstains(records, gold)

    assert result["correct"] == []
    assert result["structurally_unreachable"] == ["A"]
    assert result["reachable_miss"] == []


def test_structurally_unreachable_when_gold_expects_answer_with_assumption_and_no_reason():
    # ANSWER_WITH_ASSUMPTION cases whose gold reason_code is None can
    # never match, since a real pipeline abstain always sets some
    # reason_code -- there is no "state an assumption" mechanism.
    gold = {"A": _gold("A", "ANSWER_WITH_ASSUMPTION", None)}
    records = [_record("A", None, "UNGROUNDED_ANSWER")]

    result = categorize_abstains(records, gold)

    assert result["structurally_unreachable"] == ["A"]


def test_reachable_miss_when_both_codes_are_real_pipeline_codes_but_differ():
    gold = {"A": _gold("A", "ABSTAIN", "OUT_OF_SCOPE")}
    records = [_record("A", None, "LOW_AGREEMENT")]

    result = categorize_abstains(records, gold)

    assert result["correct"] == []
    assert result["structurally_unreachable"] == []
    assert result["reachable_miss"] == ["A"]


def test_shouldnt_have_abstained_grouped_by_reason_code():
    gold = {
        "A": _gold("A", "ANSWER"),
        "B": _gold("B", "ANSWER"),
    }
    records = [
        _record("A", None, "LOW_AGREEMENT"),
        _record("B", None, "UNGROUNDED_ANSWER"),
    ]

    result = categorize_abstains(records, gold)

    assert result["shouldnt_have_abstained"] == {
        "LOW_AGREEMENT": ["A"],
        "UNGROUNDED_ANSWER": ["B"],
    }


def test_missed_abstain_when_expected_to_abstain_but_answered():
    gold = {"A": _gold("A", "ABSTAIN", "SCHEMA_MISMATCH")}
    records = [_record("A", "here is an answer", None)]

    result = categorize_abstains(records, gold)

    assert result["missed_abstain"] == ["A"]
    assert result["correct"] == []


def test_answered_and_expected_answer_is_not_categorized_anywhere():
    gold = {"A": _gold("A", "ANSWER")}
    records = [_record("A", "a correct answer", None)]

    result = categorize_abstains(records, gold)

    assert result == {
        "correct": [],
        "structurally_unreachable": [],
        "reachable_miss": [],
        "shouldnt_have_abstained": {},
        "missed_abstain": [],
    }


def test_format_report_includes_counts_and_case_ids():
    categories = {
        "correct": ["A"],
        "structurally_unreachable": ["B", "C"],
        "reachable_miss": ["D"],
        "shouldnt_have_abstained": {"LOW_AGREEMENT": ["E"], "UNGROUNDED_ANSWER": ["F", "G"]},
        "missed_abstain": ["H"],
    }

    report = format_report(categories)

    assert "correct: 1" in report
    assert "structurally unreachable: 2" in report
    assert "B, C" in report
    assert "reachable miss: 1" in report
    assert "LOW_AGREEMENT: 1" in report
    assert "E" in report
    assert "UNGROUNDED_ANSWER: 2" in report
    assert "F, G" in report
    assert "missed abstain (answered when it should have abstained): 1" in report
    assert "H" in report


def test_main_reads_jsonl_and_gold_files_and_prints_report(tmp_path, capsys):
    from evals.diagnose_abstains import main

    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps({"id": "A", "expected": "ABSTAIN", "reason_code": "OUT_OF_SCOPE"}) + "\n"
    )

    report_path = tmp_path / "eval_2026-01-01.jsonl"
    report_path.write_text(
        json.dumps({"id": "A", "answer": None, "reason_code": "OUT_OF_SCOPE"}) + "\n"
    )

    exit_code = main([str(report_path), "--gold", str(gold_path)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "correct: 1" in captured.out
