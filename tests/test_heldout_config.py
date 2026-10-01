import json

import pytest

from evals import heldout_config as C
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
    assert "rule" in link and "+2" in link["rule"]
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


@pytest.mark.parametrize(
    "net_30b,net_xiyan,decision",
    [
        (2, 0, "on"),
        (5, 3, "on"),
        (1, 0, "off"),
        (3, -1, "off"),
        (0, 0, "off"),
        (2, -2, "off"),
        (-1, 4, "off"),
    ],
)
def test_the_pre_registered_linker_rule_is_applied_exactly(net_30b, net_xiyan, decision):
    out, reason = C.apply_rule(net_30b, net_xiyan)
    assert out == decision
    assert f"{net_30b:+d}" in reason and f"{net_xiyan:+d}" in reason
