import json
from pathlib import Path

import pytest

from evals import heldout_config as C
from evals.rescore_v2 import Cand, Pool
from evals.scoring import FrozenGoldError


def test_the_declaration_file_has_one_active_configuration_pinned_to_a_commit_and_a_code_tree():
    decls = C.load()
    assert [d["id"] for d in decls] == ["H1", "H2", "H3"]
    h = C.active(decls)
    assert h["id"] == "H3" and h["supersedes"] == "H2"
    assert len(h["code_commit"]) == 40 and len(h["ledgerql_tree"]) == 40
    assert h["models"]["primary"] == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    assert h["models"]["policy_partner"] == "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"
    assert h["settings"]["exec_error_repair"] == "off" and h["settings"]["year_verifier"] == "on"
    assert set(h["jobs"]) == {"primary", "policy_partner"}


def test_a_superseded_declaration_keeps_what_it_pinned():
    # Declarations are append-only: superseding H1 changes its status and nothing it declared.
    h1, h2, _ = C.load()
    assert h1["status"] == "superseded" and h1["superseded_by"] == "H2"
    assert h1["code_commit"] == "97c69949a491d97146635c0dd45fd55d934f8a1c"
    assert h1["ledgerql_tree"] == "95ad19d17eeac9debf36e48903d4d6371962373d"
    assert h2["ledgerql_tree"] != h1["ledgerql_tree"] and len(h2["changes_from_H1"]) == 2
    # H2 was amended once, before anything ran under it; what it first pinned is kept
    first = h2["amended"]["first_declared_as"]
    assert first["ledgerql_tree"] == "720f4bae3a5a33644812ef1dd54db8e1cfc7ec25"
    assert (
        first["ledgerql_tree"] != h2["ledgerql_tree"]
        and h2["amended"]["why_an_amendment_and_not_H3"]
    )
    # one declaration covers both changes, and the linker decision is carried over unchanged
    assert h2["entity_link"] == h1["entity_link"] and h2["entity_link"]["decision"] == "on"
    assert h2["models"] == h1["models"] and h2["jobs"] == h1["jobs"]
    assert {k: v for k, v in h2["settings"].items() if k in h1["settings"]} == h1["settings"]


def test_h3_changes_the_verifier_only_and_keeps_everything_else_h2_pinned():
    _, h2, h3 = C.load()
    assert h2["status"] == "superseded" and h2["superseded_by"] == "H3"
    assert h2["code_commit"] == "590188e3ace789fea9e2ef8816ae4444baf5ff83"
    assert h2["ledgerql_tree"] == "2cbe737057fd2c58abafd324161701dafb9896fa"
    assert h3["ledgerql_tree"] != h2["ledgerql_tree"]
    assert len(h3["changes_from_H2"]) == 1 and "ledgerql/verify.py" in h3["changes_from_H2"][0]
    assert h3["entity_link"] == h2["entity_link"] and h3["entity_link"]["decision"] == "on"
    assert h3["models"] == h2["models"] and h3["jobs"] == h2["jobs"]
    assert {k: v for k, v in h3["settings"].items() if k in h2["settings"]} == h2["settings"]
    # the offline check it was declared on: one draft changes, and it is the one the change is for
    check = h3["regression_check"]
    assert check["verdicts_changed"] == ["L11"] and check["model_runs"] == 0


def test_h3_is_final_and_ledgerql_is_frozen_until_the_heldout_runs_are_done():
    h3 = C.active(C.load())
    assert h3["final"] is True
    assert h3["frozen"]["since"] == "2026-10-04" and h3["frozen"]["lifted"] is None
    issues = C.REPO / h3["frozen"]["issues_go_to"]
    assert issues == C.REPO / "evals" / "KNOWN_PIPELINE_ISSUES.md" and Path(issues).exists()


def _with_a_successor(lifted):
    decls = json.loads(json.dumps(C.load()))
    h4 = {k: v for k, v in decls[-1].items() if k not in ("final", "frozen")}
    decls[-1].update(status="superseded", superseded_by="H4")
    decls[-1]["frozen"]["lifted"] = lifted
    return [*decls, {**h4, "id": "H4", "supersedes": "H3"}]


def test_a_configuration_declared_after_the_final_one_is_refused_while_the_freeze_holds():
    with pytest.raises(ValueError, match="frozen.*KNOWN_PIPELINE_ISSUES"):
        C.active(_with_a_successor(lifted=None))
    # the freeze is lifted by recording when, after the held-out runs; then a successor is allowed
    assert C.active(_with_a_successor(lifted="2026-11-01"))["id"] == "H4"


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
        f"ledgerql/ changed since configuration {h['id']} was declared. {h['id']} is final and "
        "ledgerql/ is frozen until the held-out runs are done: revert the change and list the "
        "issue in evals/KNOWN_PIPELINE_ISSUES.md (evals/HELDOUT_PROTOCOL.md 6a)."
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
