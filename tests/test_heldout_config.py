import json

import pytest

from evals import heldout_config as C
from evals.rescore_v2 import Cand, Pool
from evals.scoring import FrozenGoldError


def test_the_declaration_file_has_one_active_configuration_pinned_to_a_commit_and_a_code_tree():
    decls = C.load()
    assert [d["id"] for d in decls] == ["H1"]
    h = C.active(decls)
    assert len(h["code_commit"]) == 40 and len(h["ledgerql_tree"]) == 40
    assert h["models"]["primary"] == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert h["models"]["policy_partner"] == "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"
    assert h["settings"]["exec_error_repair"] == "off" and h["settings"]["year_verifier"] == "on"
    assert set(h["jobs"]) == {"primary", "policy_partner"}


def test_entity_linking_is_decided_from_the_dev_ab_by_a_rule_fixed_before_the_result():
    link = C.active(C.load())["entity_link"]
    assert link["decided_from"] == "dev A/B (gen-only, gold v3), never from held-out results"
    assert (
        "entirely below zero" in link["rule"] and "10000 resamples, seed 20261002" in link["rule"]
    )
    assert "+2" in link["rule_superseded"]  # the replaced rule is kept, not erased
    assert link["decision"] in (None, "on", "off")  # null until the dev A/B is read


def test_the_code_under_ledgerql_is_the_declared_tree_or_a_new_configuration_must_be_declared():
    h = C.active(C.load())
    assert C.current_tree() == h["ledgerql_tree"], (
        "ledgerql/ changed since configuration H1 was declared. A change is a new configuration: "
        "declare it in evals/heldout_config.json (and the protocol) before any held-out run."
    )


def test_a_non_heldout_gold_file_is_never_checked(tmp_path, monkeypatch):
    f = tmp_path / "gold_v3.jsonl"
    f.write_text("{}\n")
    monkeypatch.setattr(C, "current_tree", lambda: "0" * 40)
    C.require_declared(f)  # not held-out: no-op


def _heldout(tmp_path):
    f = tmp_path / "heldout_v1.jsonl"
    f.write_text("{}\n")
    return f


def test_a_heldout_run_is_refused_until_the_linker_decision_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "current_tree", lambda: C.active(C.load())["ledgerql_tree"])
    with pytest.raises(FrozenGoldError, match="entity linking"):
        C.require_declared(_heldout(tmp_path), decls=_with_decision(None))


def _with_decision(decision):
    decls = json.loads(json.dumps(C.load()))
    decls[-1]["entity_link"]["decision"] = decision
    return decls


def test_a_heldout_run_is_refused_when_the_code_differs_from_the_declaration(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "current_tree", lambda: "f" * 40)
    with pytest.raises(FrozenGoldError, match="declared"):
        C.require_declared(_heldout(tmp_path), decls=_with_decision("off"))


def test_a_heldout_run_is_refused_when_the_linker_env_disagrees_with_the_decision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(C, "current_tree", lambda: C.active(C.load())["ledgerql_tree"])
    monkeypatch.setenv("LEDGERQL_ENTITY_LINK", "1")
    with pytest.raises(FrozenGoldError, match="LEDGERQL_ENTITY_LINK"):
        C.require_declared(_heldout(tmp_path), decls=_with_decision("off"))
    monkeypatch.delenv("LEDGERQL_ENTITY_LINK")
    C.require_declared(_heldout(tmp_path), decls=_with_decision("off"))  # all three agree: allowed
    monkeypatch.setenv("LEDGERQL_ENTITY_LINK", "1")
    C.require_declared(_heldout(tmp_path), decls=_with_decision("on"))


def _pool(pid, profile, verdicts):
    cands = [Cand(f"s{i}", [(i,)], OK if ok else NO) for i, ok in enumerate(verdicts)]
    return Pool("m", profile, pid, "t", cands, winner=0)


OK = {"v1": True, "v2": True, "v3": True, "v3r": True}
NO = {"v1": False, "v2": False, "v3": False, "v3r": False}


def test_the_decision_metric_is_the_change_in_the_share_of_correct_candidates_per_case():
    base = [_pool("A", "baseline", [0, 0, 0, 0, 0]), _pool("B", "baseline", [1, 1, 1, 1, 0])]
    link = [_pool("A", "linked", [1, 1, 0, 0, 0]), _pool("B", "linked", [1, 1, 0, 0, 0])]
    diffs = C.case_share_diffs(base, link)
    assert diffs == pytest.approx({"A": 0.4, "B": -0.4})


def test_the_vote_pick_does_not_enter_the_metric():
    # Same candidates, different winner index: the share is unchanged.
    a = _pool("A", "baseline", [1, 0, 0, 0, 0])
    b = _pool("A", "linked", [1, 0, 0, 0, 0])
    b.winner = 1
    assert C.case_share_diffs([a], [b]) == {"A": 0.0}


def test_conditions_over_different_cases_are_refused():
    with pytest.raises(ValueError, match="different cases"):
        C.case_share_diffs([_pool("A", "baseline", [1])], [_pool("B", "linked", [1])])


def test_the_bootstrap_is_seeded_so_the_interval_is_reproducible():
    diffs = [i / 37 - 0.4 for i in range(30)]
    assert C.bootstrap_ci(diffs) == C.bootstrap_ci(diffs)
    assert C.bootstrap_ci(diffs) != C.bootstrap_ci(diffs, seed=1)


def test_the_bootstrap_interval_brackets_the_mean_and_collapses_when_every_case_agrees():
    diffs = [0.2, 0.0, -0.2, 0.4, 0.0, 0.2, 0.0, 0.0]
    lo, hi = C.bootstrap_ci(diffs)
    assert lo <= sum(diffs) / len(diffs) <= hi
    assert C.bootstrap_ci([0.2] * 50) == (pytest.approx(0.2), pytest.approx(0.2))


def test_a_consistently_harmful_linker_is_caught_by_the_interval():
    lo, hi = C.bootstrap_ci([-0.2] * 20 + [0.0] * 30)
    assert hi < 0


@pytest.mark.parametrize(
    "ci_30b,ci_xiyan,decision",
    [
        ((0.01, 0.09), (0.00, 0.08), "on"),  # helps
        ((-0.05, 0.06), (-0.04, 0.05), "on"),  # no evidence either way: on by default
        ((-0.06, -0.01), (0.00, 0.08), "off"),  # the 30B is harmed
        ((0.01, 0.09), (-0.08, -0.02), "off"),  # XiYan is harmed
        ((-0.05, 0.0), (-0.04, 0.0), "on"),  # an upper bound of exactly zero is not "below"
        ((-0.09, -0.03), (-0.08, -0.02), "off"),
    ],
)
def test_the_amended_linker_rule_is_on_unless_either_interval_lies_entirely_below_zero(
    ci_30b, ci_xiyan, decision
):
    out, reason = C.apply_rule(ci_30b, ci_xiyan, 0.0, 0.0)
    assert out == decision
    assert f"{ci_30b[0]:+.4f}" in reason and f"{ci_xiyan[1]:+.4f}" in reason
