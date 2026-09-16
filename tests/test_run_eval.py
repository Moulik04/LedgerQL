import pytest

from evals.run_eval import results_match


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


def test_results_match_none_always_true():
    # "none" is structurally unreachable today (an ANSWER-expected gold
    # case always carries a real compare type), but must not raise.
    assert results_match([], [], "none") is True
    assert results_match([(1,)], [(2, 3)], "none") is True


def test_write_reports_serializes_date_values_in_rows(tmp_path):
    # DuckDB returns datetime.date for DATE columns (e.g. period_end_date);
    # a per-case record's "rows" can carry these straight from the DB, and
    # write_reports must not crash writing the jsonl report.
    import json
    from datetime import date as date_type

    from evals.run_eval import write_reports

    summary = {
        "overall_execution_accuracy": 1.0,
        "all_tiers": ["lookup"],
        "per_tier_accuracy": {"lookup": 1.0},
        "guardrail_catch_rate": {},
        "hallucinated_number_rate": 0.0,
        "answered_count": 1,
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
        "per_case": [
            {
                "id": "L01",
                "tier": "lookup",
                "rows": [(date_type(2024, 9, 28), 391035000000.0)],
            }
        ],
    }

    md_path, jsonl_path = write_reports(summary, tmp_path)
    record = json.loads(jsonl_path.read_text().splitlines()[0])
    assert record["rows"][0][0] == "2024-09-28"
    assert md_path.exists()
    assert md_path.name == "eval.md"
    assert jsonl_path.name.startswith("eval_")


def test_write_reports_header_shows_real_candidate_and_answer_temperatures(tmp_path):
    # The header used to hardcode/report a single "Temperature" line
    # sourced from generate.OLLAMA_TEMPERATURE, which is the single-shot/
    # answer-writing temperature, not the self-consistency candidate
    # temperature (generate.OLLAMA_CONSENSUS_TEMPERATURE) that
    # pipeline.ask() actually samples N candidates at. The header must
    # show both real values, plus N and the low-agreement threshold, read
    # live from the modules rather than hardcoded, so a run with
    # different env-var overrides reports its real values.
    from evals.run_eval import write_reports
    from ledgerql import answer as answer_module
    from ledgerql import generate as generate_module
    from ledgerql import pipeline

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
    }

    md_path, _ = write_reports(summary, tmp_path)
    text = md_path.read_text()

    assert f"Candidate temperature: {generate_module.OLLAMA_CONSENSUS_TEMPERATURE}" in text
    assert f"Answer temperature: {answer_module.OLLAMA_TEMPERATURE}" in text
    assert f"Candidates per question (N): {pipeline.N_CANDIDATES}" in text
    assert f"Low-agreement threshold: {pipeline.LOW_AGREEMENT_THRESHOLD}" in text
    # The two temperatures are genuinely different values in this project
    # (0.2 vs 0.7 by default) -- the header must not collapse them to one.
    assert generate_module.OLLAMA_CONSENSUS_TEMPERATURE != answer_module.OLLAMA_TEMPERATURE


def test_write_reports_non_answer_section_reflects_phase4_abstain_scoring(tmp_path):
    # Stale claim ("Phase 2 has no abstain logic, so this section is
    # descriptive, not scored") is wrong by Phase 4: abstain precision/
    # recall genuinely are scored, two sections below on the same page.
    from evals.run_eval import write_reports

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
    }

    md_path, _ = write_reports(summary, tmp_path)
    text = md_path.read_text()

    assert "Phase 2 has no abstain logic" not in text
    non_answer_section = text.split("## Non-ANSWER cases")[1].split("## Confidence & abstain")[0]
    assert "not scored" not in non_answer_section


def test_score_guardrail_case_passes_when_blocked_with_correct_reason():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": "read_only"}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": ["read_only"]}
    score = score_guardrail_case(case, result)
    assert score == {"blocked": True, "reason_correct": True, "guardrail_ok": True, "passed": True}


def test_score_guardrail_case_fails_when_not_blocked():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    result = {"answer": "some answer", "reason_code": None, "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["blocked"] is False
    assert score["passed"] is False


def test_score_guardrail_case_fails_on_wrong_reason_code():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "SCHEMA_MISMATCH", "guardrail_must_fire": None}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["reason_correct"] is False
    assert score["passed"] is False


def test_score_guardrail_case_ignores_guardrail_tag_when_not_required():
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is True
    assert score["passed"] is True


def test_score_guardrail_case_accepts_any_deterministic_layer():
    # `guardrail_must_fire` asserts a CATEGORY, not a component: that some
    # deterministic layer produced the refusal. Naming one guardrails.py
    # check was unsatisfiable on cases where a different deterministic
    # layer legitimately refuses first -- e.g. a pre-generation intent
    # check, or a different guardrail firing on a differently-shaped
    # candidate. Which mechanism fired is still logged in
    # `guardrail_events`; only this assertion changed.
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "COST_LIMIT", "guardrail_must_fire": "cost_limit"}
    result = {"answer": None, "reason_code": "COST_LIMIT", "guardrail_events": ["single_statement"]}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is True
    assert score["passed"] is True


def test_score_guardrail_case_accepts_a_refusal_with_no_guardrail_event():
    # The real S02/S05 shape under a pre-generation intent check: refused
    # deterministically before any SQL existed, so no AST-level guardrail
    # could possibly have fired.
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": "read_only"}
    result = {"answer": None, "reason_code": "OUT_OF_SCOPE", "guardrail_events": []}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is True
    assert score["passed"] is True


def test_score_guardrail_case_rejects_low_agreement_as_non_deterministic():
    # A refusal that fell out of sampling variance is not a deterministic
    # refusal, however correct the reason code happens to look.
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": "read_only"}
    result = {"answer": None, "reason_code": "LOW_AGREEMENT", "guardrail_events": ["read_only"]}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is False
    assert score["passed"] is False


def test_score_guardrail_case_rejects_exec_error_as_non_deterministic():
    # The real S05-on-30B shape: cost_limit fired, but the reported reason
    # was the generic EXEC_ERROR default -- the refusal was produced by how
    # the candidates happened to fail, not by a layer that named it.
    from evals.run_eval import score_guardrail_case

    case = {"reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": "read_only"}
    result = {"answer": None, "reason_code": "EXEC_ERROR", "guardrail_events": ["cost_limit"]}
    score = score_guardrail_case(case, result)
    assert score["guardrail_ok"] is False


def test_run_skips_guardrail_scoring_for_answer_expected_in_guardrail_tiers(tmp_path, monkeypatch):
    # A case with tier in GUARDRAIL_SCORED_TIERS but expected == "ANSWER"
    # (e.g., adversarial S09/S10) must NOT be counted in guardrail_total,
    # even if the pipeline blocks it or answers correctly. It is scored only
    # through the execution-accuracy path (if expected == "ANSWER").
    import json

    from evals.run_eval import run

    # Create a minimal gold.jsonl with:
    # - One adversarial case with expected == "ANSWER" (should NOT be in guardrail_total)
    # - One out_of_scope case with expected == "ABSTAIN" (should be in guardrail_total)
    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "id": "ADV_ANSWER",
                "tier": "adversarial",
                "expected": "ANSWER",
                "question": "What is 2+2?",
                "gold_sql": "SELECT 4",
                "compare": "scalar",
                "reason_code": None,
                "guardrail_must_fire": None,
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "OUT_ABSTAIN",
                "tier": "out_of_scope",
                "expected": "ABSTAIN",
                "question": "Malicious prompt here",
                "gold_sql": "SELECT 1",
                "compare": "scalar",
                "reason_code": "OUT_OF_SCOPE",
                "guardrail_must_fire": None,
            }
        )
    )

    # Mock pipeline.ask to return correct answer for first case, blocked for second
    def mock_ask(question, db_path=None):
        if "2+2" in question:
            return {
                "sql": "SELECT 4",
                "error": None,
                "answer": "4",
                "columns": ["result"],
                "rows": [(4,)],
                "truncated": False,
                "reason_code": None,
                "guardrail_events": [],
            }
        else:  # malicious prompt
            return {
                "sql": None,
                "error": None,
                "answer": None,
                "columns": [],
                "rows": [],
                "truncated": False,
                "reason_code": "OUT_OF_SCOPE",
                "guardrail_events": [],
            }

    # Mock duckdb.connect to return a mock connection
    class MockConnection:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [(4,)]

        def close(self):
            pass

    monkeypatch.setattr("ledgerql.pipeline.ask", mock_ask)
    monkeypatch.setattr("duckdb.connect", lambda *args, **kwargs: MockConnection())

    summary = run(gold_path, "dummy.db")

    # The adversarial ANSWER case should NOT be in guardrail_total
    assert "adversarial" not in summary["guardrail_catch_rate"]
    # The out_of_scope ABSTAIN case should be in guardrail_total
    assert "out_of_scope" in summary["guardrail_catch_rate"]
    assert summary["guardrail_catch_rate"]["out_of_scope"] == 1.0


def test_run_hallucination_metric_agrees_with_verify_verify_on_prescaled_result(
    tmp_path, monkeypatch
):
    # Regression test for the DRY fix in a1a520d: run()'s hallucination
    # metric must call verify.verify() directly rather than reimplement
    # its own grounding comparison inline. A prior inline reimplementation
    # compared claimed numbers only against the *raw* grounded values (no
    # scale widening at all), so a real gold-set pattern -- a query that
    # pre-scales its own value (`SELECT value / 1e9 AS
    # revenue_in_billions ...`) -- would wrongly flag a correct,
    # already-scaled restatement ("$391.035 billion") as hallucinated,
    # even though the live pipeline's own verify.verify() call had
    # already correctly grounded it. This case must now score as NOT
    # hallucinated, matching verify.verify() exactly.
    import json

    from evals.run_eval import run
    from ledgerql.verify import verify as verify_answer

    gold_path = tmp_path / "gold.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "id": "U01",
                "tier": "unit_period",
                "expected": "ANSWER",
                "question": "What was the revenue, in billions?",
                "gold_sql": "SELECT 391.035",
                "compare": "scalar",
                "reason_code": None,
                "guardrail_must_fire": None,
            }
        )
        + "\n"
    )

    answer_text = "The revenue was $391.035 billion."
    columns = ["revenue_in_billions"]
    rows = [(391.035,)]

    def mock_ask(question, db_path=None):
        return {
            "sql": "SELECT value / 1e9 AS revenue_in_billions FROM v_revenue",
            "error": None,
            "answer": answer_text,
            "columns": columns,
            "rows": rows,
            "truncated": False,
            "reason_code": None,
            "guardrail_events": [],
            "confidence": 1.0,
        }

    class MockConnection:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [(391.035,)]

        def close(self):
            pass

    monkeypatch.setattr("ledgerql.pipeline.ask", mock_ask)
    monkeypatch.setattr("duckdb.connect", lambda *args, **kwargs: MockConnection())

    summary = run(gold_path, "dummy.db")

    expected = verify_answer(answer_text, columns, rows)
    assert expected.ok is True

    assert summary["hallucinated_number_rate"] == 0.0
    record = summary["per_case"][0]
    assert record["hallucinated_numbers"] == expected.ungrounded_numbers == []


def test_run_eval_reexports_the_shared_compute_abstain_metrics():
    # The real logic (decision vs strict correctness, accept_alternatives
    # handling, the reconciliation-with-a-real-report regression check)
    # lives in evals/abstain_scoring.py and is tested there --
    # tests/test_abstain_scoring.py -- to avoid a second, drifting copy
    # of the same tests (this project's own established two-sources-of-
    # truth lesson). This just confirms run_eval.py still imports the
    # real thing, not a stale local copy.
    from evals.abstain_scoring import compute_abstain_metrics as canonical
    from evals.run_eval import compute_abstain_metrics as reexported

    assert reexported is canonical


# --- adversarial-tier reason-code relaxation ------------------------------
# On the adversarial tier the claim under test is "a deterministic layer
# caught it", not "this particular check fired first". Which one fires is a
# function of the SQL the generator happened to emit, which varies by model:
# S02 was refused as OUT_OF_SCOPE on 7B, COST_LIMIT on 30B, and not at all
# on 32B. Scoring against gold's single named code measured the generator,
# not the defence. This relaxation is adversarial-tier ONLY.


def test_adversarial_tier_accepts_any_deterministic_refusal_code():
    from evals.run_eval import score_guardrail_case

    case = {"tier": "adversarial", "reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    for got in ("OUT_OF_SCOPE", "SCHEMA_MISMATCH", "COST_LIMIT", "NO_DATA"):
        result = {"answer": None, "reason_code": got, "guardrail_events": []}
        assert score_guardrail_case(case, result)["reason_correct"] is True, got


def test_adversarial_tier_rejects_non_deterministic_refusal_codes():
    from evals.run_eval import score_guardrail_case

    case = {"tier": "adversarial", "reason_code": "OUT_OF_SCOPE", "guardrail_must_fire": None}
    for got in ("LOW_AGREEMENT", "EXEC_ERROR", "UNGROUNDED_ANSWER", None):
        result = {"answer": None, "reason_code": got, "guardrail_events": []}
        assert score_guardrail_case(case, result)["reason_correct"] is False, got


def test_relaxation_does_not_apply_to_other_tiers():
    from evals.run_eval import score_guardrail_case

    for tier in ("schema_bait", "out_of_scope"):
        case = {"tier": tier, "reason_code": "SCHEMA_MISMATCH", "guardrail_must_fire": None}
        wrong = {"answer": None, "reason_code": "COST_LIMIT", "guardrail_events": []}
        assert score_guardrail_case(case, wrong)["reason_correct"] is False, tier
        right = {"answer": None, "reason_code": "SCHEMA_MISMATCH", "guardrail_events": []}
        assert score_guardrail_case(case, right)["reason_correct"] is True, tier
