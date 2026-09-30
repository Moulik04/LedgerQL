import json

import duckdb

from evals import bakeoff_evidence, gold_audit
from evals.gold_v2 import build_gold_v2, load_v1

DB = "tests/fixtures/eval_fixture.duckdb"


def _case(cid):
    return next(c for c in build_gold_v2(load_v1()) if c["id"] == cid)


def _evidence(cid, *sqls, model="m", profile="current"):
    return [{"model": model, "profile": profile, "id": cid, "sqls": list(sqls)}]


def test_pack_keeps_sql_and_the_pick_and_drops_raw_replies(tmp_path):
    run = tmp_path / "47274007"
    run.mkdir()
    rec = {
        "id": "L01",
        "generated_sql": "SELECT 1",
        "reason_code": None,
        "confidence": 0.6,
        "candidates": [{"sql": "SELECT 1", "raw": "SECRET reasoning"}, {"sql": "SELECT 2"}],
    }
    for p in bakeoff_evidence.PROFILES:
        (run / f"gen_only_{p}.jsonl").write_text(json.dumps(rec) + "\n")
    packed = bakeoff_evidence.pack(tmp_path, {"47274007": "modelx"})
    assert len(packed) == 3
    assert packed[0] == {
        "run": "47274007", "model": "modelx", "profile": "current", "id": "L01",
        "sqls": ["SELECT 1", "SELECT 2"], "winner_sql": "SELECT 1",
        "reason_code": None, "agreement": 0.6,
    }  # fmt: skip
    assert "SECRET" not in json.dumps(packed)


def test_tracked_evidence_is_the_whole_bakeoff():
    records = bakeoff_evidence.load()
    assert len(records) == 450  # 3 models x 3 profiles x 50 ANSWER cases
    assert sum(len(r["sqls"]) for r in records) == 2250
    assert set(bakeoff_evidence.by_run(records)) == {
        (m, p) for m in bakeoff_evidence.RUN_MODELS.values() for p in bakeoff_evidence.PROFILES
    }


def test_outcomes_split_strict_by_identifier_relaxed_empty_and_rejected():
    # A09 v2 gold: the names of companies with revenue above $300 billion.
    con = duckdb.connect(DB, read_only=True, config={"enable_external_access": "false"})
    tickers = con.execute("SELECT DISTINCT ticker FROM v_revenue WHERE value>3e11").fetchall()
    con.close()
    ev = _evidence(
        "A09",
        "SELECT DISTINCT name FROM v_revenue WHERE value > 300000000000",  # strict via name
        "SELECT DISTINCT ticker FROM v_revenue WHERE value > 300000000000",  # strict via ticker
        "SELECT DISTINCT ticker, name FROM v_revenue WHERE value > 300000000000",  # extra column
        "SELECT DISTINCT name FROM v_revenue WHERE value > 1",  # wrong set
        "SELECT name FROM v_revenue WHERE value > 1e30",  # empty
        "SELECT nope FROM v_revenue",  # execution error
    )
    assert tickers  # the fixture is the real mart
    got = gold_audit.outcomes(ev, _case("A09"), DB)
    assert got["strict"] == 2
    assert got["strict via name"] == 1 and got["strict via ticker"] == 1
    assert (got["relaxed"], got["miss"], got["empty"], got["rejected"]) == (1, 1, 1, 1)


def test_scale_profile_tells_fraction_from_percentage():
    roa = (
        "{} FROM v_net_income n JOIN v_total_assets a ON a.cik=n.cik "
        "AND a.fiscal_year=n.fiscal_year WHERE n.ticker='MSFT' AND n.fiscal_year=2024"
    )
    ev = _evidence(
        "R02",
        roa.format("SELECT 100.0*n.value/a.value"),
        roa.format("SELECT n.value/a.value"),
        "SELECT value FROM v_cash WHERE ticker='NOPE'",
    )
    got = gold_audit.scale_profile(ev, load_v1_case("R02"), DB)
    assert dict(got) == {"percent": 1, "fraction": 1, "no rows": 1}


def load_v1_case(cid):
    return next(c for c in load_v1() if c["id"] == cid)


def test_solved_cases_counts_strict_matches_per_case():
    ev = _evidence(
        "L01",
        "SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2024",
        "SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2025",
    )
    counts = gold_audit.solved_cases(ev, {"L01": _case("L01"), "L02": _case("L02")}, DB)
    assert counts == {"L01": 1, "L02": 0}


def test_goodwill_readings_of_most_recent_10k_agree_on_the_real_mart():
    sets = gold_audit.goodwill_definitions(DB)
    assert len(sets) == 5
    reference = sets["fiscal_year"]
    assert len(reference) == 27 and all(names == reference for names in sets.values())


def test_result_clusters_group_identical_results_and_flag_rejections():
    ev = _evidence(
        "L05",
        "SELECT gics_sector FROM companies WHERE ticker='TSLA'",
        "SELECT gics_sector FROM companies WHERE ticker = 'TSLA'",
        "DROP TABLE companies",
    )
    clusters = gold_audit.result_clusters(ev, "L05", DB)
    assert [(n, k == "REJECTED/ERROR") for k, n, _ in clusters] == [(2, False), (1, True)]
