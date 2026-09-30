from pathlib import Path

import pytest

from evals import rescore_v2 as R
from evals.rescore_v2 import Cand, Gold, Pool, RecordScore
from tests.support import BRIDGES2_HINT, require_fixture

DB = "tests/fixtures/eval_fixture.duckdb"


@pytest.fixture(scope="module")
def gold():
    return Gold(DB)


def _score(id, expected, answered, v1, v2, v2r=None):
    verdict = {"v1": v1, "v2": v2, "v2r": v2 if v2r is None else v2r}
    return RecordScore(id, "t", expected, answered, v1, verdict)


def test_vote_winner_is_the_first_of_the_largest_cluster_and_none_when_nothing_ran():
    a, b = (("x",),), (("y",),)
    assert R.vote_winner([None, a, b, b, a, b]) == 2  # b has 3, first at index 2
    assert R.vote_winner([a, b]) == 0  # tie -> earliest candidate
    assert R.vote_winner([None, None]) is None


def test_gold_verdicts_score_three_ways_and_none_is_never_correct(gold):
    names = [(n,) for (n,) in gold.rows["v2"]["A09"]]  # v2 gold: the companies, by name
    assert gold.verdicts("A09", names)["v2"] is True
    assert gold.verdicts("A09", names)["v1"] is False  # v1 gold also wanted year and value
    assert gold.verdicts("A09", None) == {"v1": False, "v2": False, "v2r": False}
    assert gold.verdicts("A09", [])["v2"] is False


def test_pool_pass_at_one_uses_the_vote_pick_and_pass_at_n_any_candidate():
    ok = {"v1": True, "v2": True, "v2r": True}
    no = {"v1": False, "v2": False, "v2r": False}
    p = Pool("m", "current", "X", "t", [Cand("a", [], no), Cand("b", [], ok)], winner=0)
    assert not p.pass_at_1("v2") and p.pass_at_n("v2")
    assert not Pool("m", "current", "X", "t", [Cand("a", None, no)], winner=None).pass_at_1("v2")


def test_assumption_answers_count_only_when_given_but_answer_cases_count_the_result():
    scores = [
        _score("A", "ANSWER", answered=False, v1=True, v2=True),  # abstained after a right result
        _score("B", "ANSWER_WITH_ASSUMPTION", answered=False, v1=True, v2=True),
        _score("C", "ANSWER_WITH_ASSUMPTION", answered=True, v1=False, v2=True),
        _score("D", "ANSWER_WITH_ASSUMPTION", answered=True, v1=False, v2=False),
    ]
    assert R.accuracy(scores, "ANSWER")["v2"] == 1
    assert R.accuracy(scores, "ANSWER_WITH_ASSUMPTION") == {"v1": 0, "v2": 1, "v2r": 1, "n": 3}
    split = R.assumption_split(scores)["v2"]
    assert split == {"n": 3, "answered_correct": 1, "abstained": 1, "answered_wrong": 1}


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
    assert (acc["n"], acc["v1"], acc["v2"], acc["v2r"]) == (50, 31, 33, 41)
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
    # The vote recomputed here picks exactly the SQL the harness recorded as its winner.
    picked = [p for p in pools if p.winner is not None]
    assert picked
    for p in picked:
        assert p.cands[p.winner].guard_sql == p.recorded_winner_sql, p.id
