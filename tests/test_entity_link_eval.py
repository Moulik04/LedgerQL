import json

from evals import entity_link_eval as E
from evals.rescore_v2 import Cand, Pool

OK = {"v1": True, "v2": True, "v3": True, "v3r": True}
NO = {"v1": False, "v2": False, "v3": False, "v3r": False}


def pool(pid, profile, verdicts, empties=0):
    cands = []
    for i, ok in enumerate(verdicts):
        rows = [] if i < empties else [(i,)]
        cands.append(Cand(f"s{i}", rows, OK if ok else NO))
    p = Pool("m", profile, pid, "t", cands, winner=len(verdicts) - 1)
    return p


def test_compare_counts_cases_gained_and_lost_by_the_vote_pick_and_by_any_candidate():
    base = [
        pool("A", "baseline", [0, 0, 0]),
        pool("B", "baseline", [1, 1, 1]),
        pool("C", "baseline", [0, 0, 1]),
    ]
    link = [
        pool("A", "linked", [0, 1, 1]),
        pool("B", "linked", [0, 0, 0]),
        pool("C", "linked", [0, 0, 1]),
    ]
    r = E.compare(base, link, "v3")
    assert r["cases"] == 3
    assert (r["pass_1"]["base"], r["pass_1"]["linked"]) == (2, 2)
    assert r["pass_1"]["gained"] == ["A"] and r["pass_1"]["lost"] == ["B"]
    assert (r["pass_n"]["base"], r["pass_n"]["linked"]) == (2, 2)
    assert r["pass_n"]["gained"] == ["A"] and r["pass_n"]["lost"] == ["B"]
    assert r["candidates"] == {"base": 4, "linked": 3, "n": 9, "gained": 2, "lost": 3}


def test_compare_counts_empty_results_the_name_literal_failure_mode():
    base = [pool("A", "baseline", [0, 0, 0, 0], empties=3)]
    link = [pool("A", "linked", [1, 1, 1, 1], empties=0)]
    r = E.compare(base, link, "v3")
    assert r["empty"] == {"base": 3, "linked": 0}


def test_pack_keeps_the_sql_the_pick_and_the_hint(tmp_path):
    for name, hint in (("baseline", ""), ("linked", "HINT")):
        d = tmp_path / name
        d.mkdir()
        rec = {
            "id": "L01", "generated_sql": "SELECT 1", "reason_code": None, "confidence": 0.8,
            "entity_hint": hint, "candidates": [{"sql": "SELECT 1", "raw": "secret"}],
        }  # fmt: skip
        (d / "gen_only_current.jsonl").write_text(json.dumps(rec) + "\n")
    packed = E.pack(tmp_path / "baseline", tmp_path / "linked")
    assert [(r["profile"], r["entity_hint"]) for r in packed] == [
        ("baseline", ""),
        ("linked", "HINT"),
    ]
    assert "secret" not in json.dumps(packed)
    assert all(r["model"] == E.MODEL for r in packed)
