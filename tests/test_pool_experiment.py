import random

from evals import pool_experiment as P
from evals.rescore_v2 import Cand

OK = {"v1": True, "v2": True, "v2r": True}
NO = {"v1": False, "v2": False, "v2r": False}


def cand(rows, ok):
    return Cand("sql", rows, OK if ok else NO)


def test_select_and_score_votes_by_identical_results_and_breaks_ties_by_order():
    right, wrong = [(1,)], [(2,)]
    draw = [cand(wrong, False), cand(right, True), cand(right, True), cand(wrong, False)]
    pass_n, pass_1 = P.score_draw(draw, "v2")
    # right x2 vs wrong x2 is a tie, and the cluster seen first (wrong) wins it, as in the pipeline
    assert (pass_n, pass_1) == (True, False)
    # so with a tie the earlier candidate decides
    assert P.score_draw([cand(wrong, False), cand(right, True)], "v2") == (True, False)
    assert P.score_draw([cand(right, True), cand(wrong, False)], "v2") == (True, True)


def test_a_draw_with_nothing_executed_scores_zero_and_errors_still_fill_the_budget():
    assert P.score_draw([cand(None, False)] * 5, "v2") == (False, False)


def test_expected_scores_are_exact_when_the_pool_is_the_draw():
    pool = [("r1", cand([(1,)], True)), ("r1", cand([(2,)], False))]
    rng = random.Random(0)
    exp = P.expected_over_draws(pool, k=2, n_draws=2000, rng=rng, versions=("v2",))
    pass_n, pass_1 = exp["v2"]
    assert pass_n == 1.0  # both are drawn every time
    assert abs(pass_1 - 0.5) < 0.06  # a 1-1 vote tie is broken by a random draw order


def test_stratified_draw_takes_one_candidate_from_each_of_k_distinct_runs():
    pool = [(f"run{i}", cand([(i,)], False)) for i in range(4) for _ in range(5)]
    rng = random.Random(1)
    for _ in range(20):
        draw = P.stratified_draw(pool, k=3, rng=rng)
        assert len(draw) == 3
        assert len({run for run, _ in draw}) == 3


def test_bootstrap_ci_brackets_the_mean_and_is_deterministic():
    diffs = [1.0, 0.0, 0.5, 0.0, 1.0, 0.0, 0.5, 0.5]
    lo, hi = P.bootstrap_mean_ci(diffs, seed=0)
    assert lo <= sum(diffs) / len(diffs) <= hi
    assert P.bootstrap_mean_ci(diffs, seed=0) == (lo, hi)
