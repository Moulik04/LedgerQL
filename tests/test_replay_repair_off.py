from evals.replay_repair_off import revert_exec_error_repairs, summarize


def _record(id_, expected, *, answer, execution_correct=None, reason_code=None, trigger=None):
    return {
        "id": id_,
        "expected": expected,
        "answer": answer,
        "execution_correct": execution_correct,
        "reason_code": reason_code,
        "columns": ["value"] if answer else [],
        "rows": [(1,)] if answer else [],
        "truncated": False,
        "confidence": 1.0 if answer else None,
        "hallucinated_numbers": [] if answer else None,
        "repair": {"trigger": trigger, "sql": "SELECT 1"} if trigger else None,
    }


def test_revert_leaves_untouched_records_alone():
    records = [
        _record("A01", "ANSWER", answer="5", execution_correct=True),
        _record("S01", "ABSTAIN", answer=None, reason_code="OUT_OF_SCOPE"),
    ]
    reverted = revert_exec_error_repairs(records)
    assert reverted == records
    assert reverted[0] is records[0]
    assert reverted[1] is records[1]


def test_revert_reverses_a_rescued_exec_error_repair_to_an_abstain():
    rescued = _record(
        "T06", "ABSTAIN", answer="416 billion", execution_correct=None, trigger="exec_error"
    )
    (reverted,) = revert_exec_error_repairs([rescued])
    assert reverted["answer"] is None
    assert reverted["reason_code"] == "EXEC_ERROR"
    assert reverted["repair"] is None
    assert reverted["columns"] == [] and reverted["rows"] == []
    assert reverted["confidence"] is None
    assert "hallucinated_numbers" not in reverted


def test_revert_of_an_answer_expected_case_scores_execution_incorrect_not_absent():
    rescued = _record(
        "J05", "ANSWER", answer="wrong", execution_correct=False, trigger="exec_error"
    )
    (reverted,) = revert_exec_error_repairs([rescued])
    assert reverted["execution_correct"] is False


def test_revert_leaves_a_schema_mismatch_repair_untouched():
    # No measured Bridges-2 report has one (schema_mismatch was never
    # enabled), but the function must not touch a differently-triggered
    # repair if one ever appears.
    record = _record("H02", "ABSTAIN", answer="x", trigger="schema_mismatch")
    (reverted,) = revert_exec_error_repairs([record])
    assert reverted is record


def test_summarize_counts_a_reverted_rescue_as_a_correct_abstain_not_a_miss():
    gold = {
        "T06": {"id": "T06", "tier": "time", "expected": "ABSTAIN", "reason_code": "EXEC_ERROR"},
    }
    rescued = _record(
        "T06", "ABSTAIN", answer="416 billion", execution_correct=None, trigger="exec_error"
    )
    (reverted,) = revert_exec_error_repairs([rescued])
    summary = summarize([reverted], gold)
    assert summary["abstain_recall_decision"] == 1.0
    assert summary["repair"]["by_trigger"]["exec_error"]["attempted"] == 0
