from pathlib import Path

import pytest

from evals import rescore_v2 as R
from evals.rescore_v2 import Cand, Gold, Pool, RecordScore
from tests.support import BRIDGES2_HINT, require_fixture

DB = "tests/fixtures/eval_fixture.duckdb"


@pytest.fixture(scope="module")
def gold():
    return Gold(DB)


def _score(id, expected, answered, v1, v2, v3r=None, rubric=None):
    verdict = {"v1": v1, "v2": v2, "v3": v2, "v3r": v2 if v3r is None else v3r}
    return RecordScore(id, "t", expected, answered, v1, verdict, rubric)


def test_vote_winner_is_the_first_of_the_largest_cluster_and_none_when_nothing_ran():
    a, b = (("x",),), (("y",),)
    assert R.vote_winner([None, a, b, b, a, b]) == 2  # b has 3, first at index 2
    assert R.vote_winner([a, b]) == 0  # tie -> earliest candidate
    assert R.vote_winner([None, None]) is None


def test_gold_verdicts_score_three_ways_and_none_is_never_correct(gold):
    names = [(n,) for (n,) in gold.rows["v2"]["A09"]]  # v2 gold: the companies, by name
    assert gold.verdicts("A09", names)["v2"] is True
    assert gold.verdicts("A09", names)["v1"] is False  # v1 gold also wanted year and value
    assert gold.verdicts("A09", None) == dict.fromkeys(("v1", "v2", "v3", "v3r"), False)
    assert gold.verdicts("A09", [])["v2"] is False


def test_pool_pass_at_one_uses_the_vote_pick_and_pass_at_n_any_candidate():
    ok = dict.fromkeys(("v1", "v2", "v3", "v3r"), True)
    no = dict.fromkeys(("v1", "v2", "v3", "v3r"), False)
    p = Pool("m", "current", "X", "t", [Cand("a", [], no), Cand("b", [], ok)], winner=0)
    assert not p.pass_at_1("v3") and p.pass_at_n("v3")
    assert not Pool("m", "current", "X", "t", [Cand("a", None, no)], winner=None).pass_at_1("v3")


def test_assumption_answers_count_only_when_given_but_answer_cases_count_the_result():
    scores = [
        _score("A", "ANSWER", answered=False, v1=True, v2=True),  # abstained after a right result
        _score("B", "ANSWER_WITH_ASSUMPTION", answered=False, v1=True, v2=True),
        _score("C", "ANSWER_WITH_ASSUMPTION", answered=True, v1=False, v2=True),
        _score("D", "ANSWER_WITH_ASSUMPTION", answered=True, v1=False, v2=False),
    ]
    assert R.accuracy(scores, "ANSWER")["v3"] == 1
    assert R.accuracy(scores, "ANSWER_WITH_ASSUMPTION") == {
        "v1": 0, "v2": 1, "v3": 1, "v3r": 1, "n": 3
    }  # fmt: skip
    split = R.assumption_split(scores)["v3"]
    assert (split["n"], split["answered_correct"], split["abstained"], split["answered_wrong"]) == (
        3, 1, 1, 1
    )  # fmt: skip


def test_a_correct_assumption_answer_splits_into_stated_not_stated_and_unassessed():
    scores = [
        _score("A", "ANSWER_WITH_ASSUMPTION", True, True, True, rubric=True),
        _score("B", "ANSWER_WITH_ASSUMPTION", True, True, True, rubric=False),
        _score("C", "ANSWER_WITH_ASSUMPTION", True, True, True, rubric=None),
        _score(
            "D", "ANSWER_WITH_ASSUMPTION", True, False, False, rubric=True
        ),  # stated, wrong value
        _score("E", "ANSWER_WITH_ASSUMPTION", False, False, False, rubric=None),  # abstained
    ]
    sp = R.assumption_split(scores)["v3"]
    assert (sp["answered_correct"], sp["stated"], sp["not_stated"], sp["unassessed"]) == (
        3,
        1,
        1,
        1,
    )
    assert (sp["abstained"], sp["answered_wrong"]) == (1, 1)  # the stated-but-wrong D is wrong


def test_verdict_changes_reports_gains_and_losses():
    scores = [
        _score("G", "ANSWER", True, v1=False, v2=True),
        _score("L", "ANSWER", True, v1=True, v2=False),
        _score("S", "ANSWER", True, v1=True, v2=True),
    ]
    assert [s.id for s in R.verdict_changes(scores)] == ["G", "L"]


def test_v1_reproduces_the_recorded_phase5_figures_and_v2_moves_them(gold):
    """v1 through the new path equals the published numbers exactly (the measured 30B
    run, 31/50 recorded); v2 is the new figure."""
    path = require_fixture(Path("reports/eval_bridges2_qwen3_30b_measured.jsonl"), BRIDGES2_HINT)
    scores = R.score_report(R.load_report(path), gold)
    acc = R.accuracy(scores, "ANSWER")
    assert (acc["n"], acc["v1"], acc["v2"], acc["v3"], acc["v3r"]) == (50, 31, 33, 33, 41)
    assert all(s.verdict["v1"] == s.recorded for s in scores)  # v1 recomputed == recorded


def test_bakeoff_v1_reproduces_the_published_cell_and_the_vote_matches_the_harness(gold):
    """XiYanSQL-32B on the `current` prompt: v1 34 -> 35 is the published bake-off cell."""
    evidence = [
        r for r in R.load_evidence() if (r["model"], r["profile"]) == ("xiyan_32b", "current")
    ]
    assert len(evidence) == 50
    pools = R.score_bakeoff(evidence, gold)
    cell = R.passn_table(pools)[("xiyan_32b", "current")]
    assert cell["v1"] == (34, 35)
    assert cell["v2"] == (40, 40)
    assert cell["v3"] == (41, 41)  # the pivot rule credits one more "side by side" answer
    # The vote recomputed here picks exactly the SQL the harness recorded as its winner.
    picked = [p for p in pools if p.winner is not None]
    assert picked
    for p in picked:
        assert p.cands[p.winner].guard_sql == p.recorded_winner_sql, p.id


def test_an_abstain_that_states_the_documented_reason_is_counted_apart_from_a_bare_abstain():
    scores = [
        _score(
            "R07", "ANSWER_WITH_ASSUMPTION", False, False, False, rubric=True
        ),  # abstained, reason stated
        _score(
            "H06", "ANSWER_WITH_ASSUMPTION", False, False, False, rubric=False
        ),  # abstained, wrong reason
        _score(
            "L03", "ANSWER_WITH_ASSUMPTION", False, False, False, rubric=None
        ),  # abstained, no refusal item
        _score("U02", "ANSWER_WITH_ASSUMPTION", True, True, True, rubric=True),
    ]
    sp = R.assumption_split(scores)["v3"]
    assert sp["abstained"] == 3 and sp["abstained_reason_stated"] == 1
    assert sp["stated"] == 1  # only the answer counts toward the headline


def test_an_old_abstain_record_with_no_refusal_text_gets_the_deterministic_one_replayed(gold):
    rec = {
        "id": "R07", "tier": "ratio", "expected": "ANSWER_WITH_ASSUMPTION", "answer": None,
        "reason_code": "NO_DATA", "rows": None, "execution_error": None, "execution_correct": False,
    }  # fmt: skip
    (score,) = R.score_report([rec], gold, judge=lambda q, a, t: True)
    assert (
        score.rubric_pass is True
    )  # the replayed text states the documented gap, the judge agrees
    assert R.assumption_split([score])["v3"]["abstained_reason_stated"] == 1
    (none,) = R.score_report([rec], gold)  # without a judge the judge-primary item is not assessed
    assert none.rubric_pass is None


def test_a_baseline_run_does_not_get_the_new_refusal_text_replayed_onto_its_abstains(gold):
    rec = {
        "id": "R07", "tier": "ratio", "expected": "ANSWER_WITH_ASSUMPTION", "answer": None,
        "reason_code": "NO_DATA", "rows": None, "execution_error": None,
    }  # fmt: skip
    yes = lambda q, a, t: True  # noqa: E731 - R07's item is judge-decided
    (replayed,) = R.score_report([rec], gold, judge=yes)
    assert replayed.rubric_pass is True  # the registry's sentence states the documented gap
    (baseline,) = R.score_report([rec], gold, judge=yes, replay_refusal=False)
    assert baseline.rubric_pass is None  # an old abstain had no text, so there is nothing to grade


def _evidence(sql="SELECT ticker FROM companies LIMIT 1"):
    return [{"model": "m", "profile": "baseline", "id": "A09", "sqls": [sql, sql]}]


def test_a_candidate_that_times_out_is_never_scored_as_wrong_it_stops_the_run(gold, monkeypatch):
    from evals import offline_exec as O

    timed_out = O.Outcome("timeout", error="query timed out after 120.0s", attempts=3)
    monkeypatch.setattr(R.offline_exec, "run_candidate", lambda sql, db: timed_out)
    with pytest.raises(O.ScoringIncomplete, match="m/baseline/A09#0"):
        R.score_bakeoff(_evidence(), gold)


def test_a_non_strict_run_records_the_timeout_as_its_own_status(gold, monkeypatch):
    from evals import offline_exec as O

    timed_out = O.Outcome("timeout", error="query timed out after 120.0s", attempts=3)
    monkeypatch.setattr(R.offline_exec, "run_candidate", lambda sql, db: timed_out)
    (pool,) = R.score_bakeoff(_evidence(), gold, strict=False)
    assert [c.status for c in pool.cands] == ["timeout", "timeout"]
    assert pool.cands[0].attempts == 3 and pool.cands[0].rows is None


def test_a_deterministic_sql_error_is_scored_wrong_with_status_error_and_does_not_stop(gold):
    (pool,) = R.score_bakeoff(
        _evidence("SELECT CAST(name AS INTEGER) FROM companies LIMIT 1"), gold
    )
    assert [c.status for c in pool.cands] == ["error", "error"]
    assert not pool.pass_at_n("v3")
