import json
from pathlib import Path

from evals import replay_derived as rd
from tests.support import BRIDGES2_HINT, require_fixture

GOLD = {
    "A": {"id": "A", "expected": "ABSTAIN", "reason_code": "NO_DATA", "question": "q a"},
    "B": {"id": "B", "expected": "ANSWER", "reason_code": None, "question": "q b"},
    "C": {"id": "C", "expected": "ABSTAIN", "reason_code": "SCHEMA_MISMATCH", "question": "q c"},
}
ANCHORED = "SELECT value FROM v_revenue WHERE ticker = 'NVDA' AND fiscal_year = 2025"
SET_SQL = "SELECT name FROM v_total_assets WHERE fiscal_year = 2024 AND value < 0"


def rec(i, sql, rows, *, answered=True, reason=None, conf=1.0):
    return {
        "id": i,
        "generated_sql": sql,
        "rows": rows,
        "confidence": conf,
        "answer": "x" if answered else None,
        "reason_code": reason,
    }


def test_naive_rule_flips_every_empty_answer_including_the_one_that_is_a_valid_answer():
    # The §1b finding: a blind "empty -> NO_DATA" breaks G06-shaped cases.
    recs = [rec("A", ANCHORED, []), rec("B", SET_SQL, [])]
    out, flips = rd.apply_naive_empty_rule(recs)
    assert flips == ["A", "B"]
    assert all(r["reason_code"] == "NO_DATA" and r["answer"] is None for r in out)


def test_entity_bound_rule_leaves_a_set_query_alone():
    recs = [rec("A", ANCHORED, []), rec("B", SET_SQL, [])]
    out, flips = rd.apply_entity_bound_rule(recs)
    assert flips == ["A"]
    assert out[1]["answer"] is not None and out[1]["reason_code"] is None


def test_entity_bound_rule_reaches_a_low_agreement_abstain_upper_bound_only():
    recs = [rec("A", ANCHORED, [], answered=False, reason="LOW_AGREEMENT", conf=0.2)]
    _, upper = rd.apply_entity_bound_rule(recs)
    _, lower = rd.apply_entity_bound_rule(recs, lower_bound=True)
    assert upper == ["A"] and lower == []


def test_lower_bound_keeps_only_records_where_unanimity_is_implied():
    recs = [rec("A", ANCHORED, [], conf=1.0), rec("C", ANCHORED, [], conf=0.8)]
    _, upper = rd.apply_entity_bound_rule(recs)
    _, lower = rd.apply_entity_bound_rule(recs, lower_bound=True)
    assert upper == ["A", "C"] and lower == ["A"]


def test_tautology_rule_maps_a_constant_false_answer_to_schema_mismatch():
    recs = [rec("C", "SELECT NULL AS credit_rating WHERE 1 = 0", [])]
    out, flips = rd.apply_tautology_rule(recs)
    assert flips == ["C"] and out[0]["reason_code"] == "SCHEMA_MISMATCH"


def test_rules_do_not_mutate_their_input():
    recs = [rec("A", ANCHORED, [])]
    rd.apply_naive_empty_rule(recs)
    rd.apply_entity_bound_rule(recs)
    assert recs[0]["answer"] == "x" and recs[0]["reason_code"] is None


# --- pinned against the real Bridges-2 reports. If a file is absent the test
# FAILS (tests.support.require_fixture): it is evidence and must be tracked.
REPORT = Path("reports/eval_bridges2_qwen3_30b.jsonl")
REPORT_32B = Path("reports/eval_bridges2_qwen25_32b.jsonl")


def _gold():
    return {json.loads(line)["id"]: json.loads(line) for line in open("evals/gold.jsonl")}


def test_spec_1b_and_1f_figures_reproduce_on_the_real_30b_report():
    require_fixture(REPORT, hint=BRIDGES2_HINT)
    rows = {r["label"]: r for r in rd.derive_table(REPORT, _gold())}
    base = rows["baseline (+intent)"]
    assert (round(base["precision_decision"], 3), round(base["recall_decision"], 3)) == (
        0.719,
        0.618,
    )
    assert (base["reason_correct"], base["reason_denominator"]) == (13, 23)
    naive = rows["naive: any empty/all-NULL -> NO_DATA"]
    assert (round(naive["precision_decision"], 3), round(naive["recall_decision"], 3)) == (
        0.755,
        0.912,
    )
    assert naive["g06_answered"] is False  # the finding: it breaks G06
    upper = rows["entity-bound NO_DATA (upper bound)"]
    lower = rows["entity-bound NO_DATA (lower bound)"]
    assert (
        round(upper["recall_decision"], 3),
        upper["reason_correct"],
        upper["reason_denominator"],
    ) == (0.853, 19, 35)
    assert (
        round(lower["precision_decision"], 3),
        lower["reason_correct"],
        lower["reason_denominator"],
    ) == (0.773, 19, 34)
    assert upper["g06_answered"] is True and lower["g06_answered"] is True
    taut = rows["+ tautology check (upper bound)"]
    assert (
        round(taut["recall_decision"], 3),
        taut["reason_correct"],
        taut["reason_denominator"],
    ) == (0.912, 21, 37)


def test_spec_1b_and_1f_figures_reproduce_on_the_real_32b_report():
    # The 32B tracked baseline had no reader or pinning test until this one --
    # its DECISIONS.md §2 derived figures (53.3%/73.5%) were checked once and
    # never regression-protected, the class of gap "reproducibility
    # corrections found on the way" exists to close. Mirrors the 30B test
    # above; the two reports are separate models and not expected to agree.
    require_fixture(REPORT_32B, hint=BRIDGES2_HINT)
    rows = {r["label"]: r for r in rd.derive_table(REPORT_32B, _gold())}
    base = rows["baseline (+intent)"]
    assert (
        round(base["recall_decision"], 3),
        base["reason_correct"],
        base["reason_denominator"],
    ) == (
        0.735,
        16,
        30,
    )
    assert round(base["reason_code_accuracy"], 3) == 0.533
    naive = rows["naive: any empty/all-NULL -> NO_DATA"]
    assert naive["g06_answered"] is False  # the finding holds on this model too
    upper = rows["entity-bound NO_DATA (upper bound)"]
    lower = rows["entity-bound NO_DATA (lower bound)"]
    assert round(upper["recall_decision"], 3) == 0.912
    assert round(lower["recall_decision"], 3) == 0.882
    assert upper["g06_answered"] is True and lower["g06_answered"] is True
