from evals.repair_scoring import compute_repair_stats

CASES = {
    "A1": {"id": "A1", "expected": "ANSWER"},
    "A2": {"id": "A2", "expected": "ANSWER"},
    "W1": {"id": "W1", "expected": "ANSWER_WITH_ASSUMPTION"},
    "X1": {"id": "X1", "expected": "ABSTAIN"},
    "X2": {"id": "X2", "expected": "ABSTAIN"},
}


def _rec(case_id, trigger, answered, correct=None):
    rec = {
        "id": case_id,
        "answer": "an answer" if answered else None,
        "repair": None if trigger is None else {"trigger": trigger, "sql": "SELECT 1"},
    }
    if correct is not None:
        rec["execution_correct"] = correct
    return rec


def test_stats_are_split_by_trigger_with_all_triggers_always_present():
    stats = compute_repair_stats([], CASES)
    assert set(stats["by_trigger"]) == {"exec_error", "schema_mismatch"}
    assert stats["by_trigger"]["exec_error"]["attempted"] == 0
    assert stats["by_trigger"]["exec_error"]["rescue_rate"] == 0.0


def test_rescued_means_the_repair_turned_an_abstain_into_an_answer():
    records = [
        _rec("A1", "exec_error", answered=True, correct=True),
        _rec("A2", "exec_error", answered=True, correct=False),
        _rec("W1", "exec_error", answered=False),
        _rec("A1", None, answered=True, correct=True),  # never repaired: ignored
    ]
    s = compute_repair_stats(records, CASES)["by_trigger"]["exec_error"]
    assert s["attempted"] == 3
    assert s["rescued"] == 2
    assert s["rescued_correct"] == 1
    assert round(s["rescue_rate"], 3) == round(2 / 3, 3)


def test_rescuing_a_case_that_should_have_abstained_is_counted_as_harm_not_success():
    # A repair that turns a correct refusal into an answer is the failure mode
    # this trigger set risks; it must be visible on its own, not folded in.
    records = [
        _rec("X1", "schema_mismatch", answered=True),
        _rec("X2", "schema_mismatch", answered=False),
    ]
    s = compute_repair_stats(records, CASES)["by_trigger"]["schema_mismatch"]
    assert s["attempted"] == 2
    assert s["rescued"] == 1
    assert s["rescued_should_have_abstained"] == 1
    assert s["rescued_correct"] == 0


def test_totals_sum_the_triggers():
    records = [
        _rec("A1", "exec_error", answered=True, correct=True),
        _rec("A2", "schema_mismatch", answered=False),
        _rec("X1", "schema_mismatch", answered=True),
    ]
    total = compute_repair_stats(records, CASES)["total"]
    assert total["attempted"] == 3 and total["rescued"] == 2
    assert total["rescued_correct"] == 1 and total["rescued_should_have_abstained"] == 1


def test_report_renders_a_repair_section_per_trigger(tmp_path):
    from evals.run_eval import write_reports

    stats = compute_repair_stats([_rec("A1", "exec_error", answered=True, correct=True)], CASES)
    summary = {
        "overall_execution_accuracy": 0.0,
        "all_tiers": [],
        "per_tier_accuracy": {},
        "guardrail_catch_rate": {},
        "hallucinated_number_rate": 0.0,
        "answered_count": 0,
        "non_answer_case_count": 0,
        "non_answer_attempted": 0,
        "non_answer_errored": 0,
        "non_answer_tier_breakdown": {},
        "always_abstain_baseline": 0.0,
        "all_abstains": 0,
        "required_abstain_cases": 0,
        "assumption_cases": 0,
        "decision_correct_abstains": 0,
        "strict_correct_abstains": 0,
        "required_abstains_caught": 0,
        "required_abstains_caught_strict": 0,
        "assumption_cases_handled": 0,
        "assumption_case_handling": 0.0,
        "abstain_precision_decision": 0.0,
        "abstain_precision_strict": 0.0,
        "abstain_recall_decision": 0.0,
        "abstain_recall_strict": 0.0,
        "reason_code_accuracy": 0.0,
        "per_case": [],
        "repair": stats,
    }
    md_path, _ = write_reports(summary, tmp_path)
    text = md_path.read_text()
    assert "## Repair" in text
    for trigger in ("exec_error", "schema_mismatch"):
        assert trigger in text


def test_a_retired_trigger_in_an_old_report_gets_its_own_bucket_not_dropped():
    # empty_entity_bound was cut on 2026-09-20; reports written while it existed
    # still carry it. Nothing may be silently dropped from the tally.
    records = [_rec("A1", "empty_entity_bound", answered=False)]
    stats = compute_repair_stats(records, CASES)
    assert stats["by_trigger"]["empty_entity_bound"]["attempted"] == 1
    assert stats["total"]["attempted"] == 1
