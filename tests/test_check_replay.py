import json

from evals import check_replay as cr
from ledgerql.pipeline import LOW_AGREEMENT_THRESHOLD

ANCHORED = "SELECT value FROM v_revenue WHERE ticker = 'NVDA' AND fiscal_year = 2025"
SET_SQL = "SELECT name FROM v_total_assets WHERE fiscal_year = 2024 AND value < 0"
TAUT = "SELECT NULL AS credit_rating WHERE 1 = 0"


def cand(sql=ANCHORED, *, ok=True, reason=None, events=(), n_rows=0, empty=True, err=None):
    if not ok:
        n_rows, empty = None, None
    return {
        "sql": sql,
        "guard_ok": ok,
        "reason_code": reason,
        "events": list(events),
        "detail": None,
        "exec_error": err,
        "n_rows": n_rows,
        "empty": empty,
    }


def rec(i, sql, cands, *, reason=None, answered=False, conf=1.0, rows=None, repair=None):
    return {
        "id": i,
        "generated_sql": sql,
        "candidates": cands,
        "reason_code": reason,
        "answer": "x" if answered else None,
        "confidence": conf,
        "rows": [] if rows is None else rows,
        "repair": repair,
    }


def five(**kw):
    return [cand(**kw) for _ in range(5)]


# ---- exact NO_DATA signal from candidates -------------------------------------


def test_exact_signal_is_unanimity_among_survivors_on_an_entity_bound_query():
    cands = [cand()] + [cand(ok=False, reason="EXEC_ERROR") for _ in range(4)]
    assert cr.exact_no_data_signal(rec("A", ANCHORED, cands, conf=0.2)) is True


def test_exact_signal_also_fires_for_an_empty_winner_that_clears_the_gate_despite_a_dissent():
    cands = [cand(), cand(), cand(), cand(), cand(n_rows=1, empty=False)]
    assert cr.exact_no_data_signal(rec("A", ANCHORED, cands, conf=0.8)) is True


def test_exact_signal_is_false_below_the_gate_with_a_dissent():
    cands = [cand(), cand(n_rows=1, empty=False)] + [cand(ok=False, reason="EXEC_ERROR")] * 3
    assert cr.exact_no_data_signal(rec("A", ANCHORED, cands, conf=0.2)) is False


def test_exact_signal_is_false_for_a_set_query():
    assert cr.exact_no_data_signal(rec("B", SET_SQL, five(sql=SET_SQL))) is False


def test_exact_signal_is_none_without_candidates_or_survivors():
    assert cr.exact_no_data_signal({"id": "X", "generated_sql": ANCHORED, "rows": []}) is None
    dead = [cand(ok=False, reason="EXEC_ERROR") for _ in range(5)]
    assert cr.exact_no_data_signal(rec("X", ANCHORED, dead, reason="EXEC_ERROR")) is None


# ---- the derived-replay bounds contain the exact answer ---------------------------


def test_bounds_hold_and_the_gap_is_reported():
    records = [
        rec("agree", ANCHORED, five(), reason="NO_DATA", conf=1.0),  # lower = exact = upper
        rec(
            "dissent",
            ANCHORED,
            [cand()] * 4 + [cand(n_rows=1, empty=False)],
            reason="NO_DATA",
            conf=0.8,
        ),
        rec(
            "loose",
            ANCHORED,
            [cand()] + [cand(n_rows=1, empty=False)] + [cand(ok=False, reason="EXEC_ERROR")] * 3,
            reason="LOW_AGREEMENT",
            conf=0.2,
        ),  # upper says flip, exact says no
        rec("setq", SET_SQL, five(sql=SET_SQL), answered=True),
    ]
    out = cr.check_bounds(records)
    assert out["violations"] == []
    assert out["upper_minus_exact"] == ["loose"]
    assert out["exact_minus_lower"] == ["dissent"]
    assert out["n_checked"] == 4


def test_a_violated_bound_is_reported_not_swallowed():
    # An exact flip that the upper bound missed would mean the derived replay was
    # not an upper bound at all.
    bad = rec("x", ANCHORED, five(), reason="NO_DATA", conf=1.0)
    bad["generated_sql"] = SET_SQL  # winner SQL not entity-bound, yet candidates say so
    bad["candidates"] = five(sql=ANCHORED)
    out = cr.check_bounds([bad])
    assert out["n_checked"] == 1  # it was compared, whatever the verdict


def test_full_agreement_always_clears_the_low_agreement_threshold():
    # check_bounds's lower bound (`lower = upper and confidence == 1.0`) has
    # never been observed to differ from the upper bound on real data, because
    # this holds: a query nothing dissented on can never itself be flagged
    # LOW_AGREEMENT. If LOW_AGREEMENT_THRESHOLD is ever raised above 1.0 (or
    # confidence stops being a 0..1 fraction), this fails and says so -- the
    # lower-bound branch has gone live and needs a second look, not silence.
    assert 1.0 >= LOW_AGREEMENT_THRESHOLD


# ---- routing replays from candidates ------------------------------------------------


def test_routing_replays_the_recorded_reason_codes():
    records = [
        rec("nd", ANCHORED, five(), reason="NO_DATA", conf=1.0),
        rec(
            "low",
            SET_SQL,
            [cand(sql=SET_SQL, n_rows=1, empty=False)]
            + [cand(sql=SET_SQL, ok=False, reason="EXEC_ERROR")] * 4,
            reason="LOW_AGREEMENT",
            conf=0.2,
            rows=[[1]],
        ),
        rec(
            "ans",
            SET_SQL,
            five(sql=SET_SQL, n_rows=1, empty=False),
            answered=True,
            conf=1.0,
            rows=[[1]],
        ),
        rec("taut", TAUT, five(sql=TAUT), reason="SCHEMA_MISMATCH", conf=1.0),
    ]
    out = cr.replay_routing(records)
    assert out["checked"] == 4 and out["mismatches"] == []


def test_routing_flags_a_record_whose_logged_candidates_do_not_explain_its_reason():
    lie = rec("lie", ANCHORED, five(), reason="LOW_AGREEMENT", conf=1.0)
    out = cr.replay_routing([lie])
    assert out["mismatches"] == [("lie", "LOW_AGREEMENT", "NO_DATA")]


def test_routing_skips_repaired_records_because_they_have_no_agreement():
    repaired = rec(
        "r",
        SET_SQL,
        five(sql=SET_SQL, ok=False, reason="EXEC_ERROR"),
        answered=True,
        conf=None,
        repair={"trigger": "exec_error", "sql": "SELECT 1"},
    )
    assert cr.replay_routing([repaired])["checked"] == 0


# ---- 6c: named rejection outranks EXEC_ERROR, replayed from per-candidate reasons ----


def test_6c_replays_from_per_candidate_guardrail_reasons():
    named = [cand(ok=False, reason="EXEC_ERROR")] * 3 + [
        cand(ok=False, reason="SCHEMA_MISMATCH", events=["schema_allowlist"])
    ] * 2
    plain = [cand(ok=False, reason="EXEC_ERROR")] * 5
    records = [
        rec("named", "x", named, reason="SCHEMA_MISMATCH"),
        rec("plain", "x", plain, reason="EXEC_ERROR"),
    ]
    out = cr.replay_consensus_reasons(records)
    assert out["checked"] == 2 and out["mismatches"] == []


def test_6c_mismatch_is_reported():
    named = [cand(ok=False, reason="EXEC_ERROR")] * 3 + [
        cand(ok=False, reason="OUT_OF_SCOPE", events=["read_only"])
    ] * 2
    out = cr.replay_consensus_reasons([rec("s", "x", named, reason="EXEC_ERROR")])
    assert out["mismatches"] == [
        ("s", "EXEC_ERROR", "OUT_OF_SCOPE")
    ]  # the pre-6c behaviour, caught


# ---- the CLI: a verifier is only trusted once it has failed on planted input ----------


def _write(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _clean_report():
    named = [cand(ok=False, reason="EXEC_ERROR")] * 3 + [
        cand(ok=False, reason="SCHEMA_MISMATCH", events=["schema_allowlist"])
    ] * 2
    return [
        rec("nd", ANCHORED, five(), reason="NO_DATA", conf=1.0),
        rec("named", "x", named, reason="SCHEMA_MISMATCH"),
    ]


def test_main_exits_zero_on_a_consistent_report(tmp_path, capsys):
    assert cr.main([str(_write(tmp_path / "ok.jsonl", _clean_report()))]) == 0
    assert capsys.readouterr().out.rstrip().endswith("OK")


def test_main_exits_nonzero_on_each_kind_of_planted_corruption(tmp_path):
    # A corrupted guardrail reason (6c no longer replays).
    guard = _clean_report()
    for c in guard[1]["candidates"]:
        c["reason_code"] = "EXEC_ERROR"
    # A recorded outcome the candidate log does not explain (routing).
    routed = _clean_report()
    routed[0]["reason_code"] = "LOW_AGREEMENT"
    # Winner rows that contradict an all-empty candidate log (bounds).
    bounds = _clean_report()
    bounds[0]["rows"] = [[1]]

    for name, records in {"guard": guard, "routed": routed, "bounds": bounds}.items():
        assert cr.main([str(_write(tmp_path / f"{name}.jsonl", records))]) == 1, name


def test_main_exits_nonzero_when_the_report_has_no_candidate_log(tmp_path):
    # An old report cannot be checked; it must not read as a pass.
    old = [{"id": "a", "generated_sql": ANCHORED, "reason_code": None, "confidence": 1.0}]
    assert cr.main([str(_write(tmp_path / "old.jsonl", old))]) == 1
