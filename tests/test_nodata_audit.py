# ruff: noqa: E501  (test SQL strings are single lines)
import json

import duckdb

from evals import nodata_audit as N

DB = "tests/fixtures/eval_fixture.duckdb"


def rec(sql_list, empties):
    return {"id": "U07", "answer": None, "reason_code": "NO_DATA", "generated_sql": sql_list[0],
            "candidates": [{"sql": s, "empty": e} for s, e in zip(sql_list, empties, strict=True)]}  # fmt: skip


def con():
    return duckdb.connect(DB, read_only=True, config={"enable_external_access": "false"})


def test_a_wrong_name_literal_is_one_that_is_not_the_stored_name():
    sqls = ["SELECT value FROM v_revenue WHERE name = 'The Coca-Cola Company' LIMIT 1",
            "SELECT value FROM v_revenue WHERE name = 'Coca-Cola Company (The)' LIMIT 1"]  # fmt: skip
    out = N.classify(rec(sqls, [True, False]), ["Coca-Cola Company (The)"], "KO", DB)
    assert out["empty"] == 1 and out["empty_with_wrong_name"] == 1 and out["all_empties_wrong_name"]


def test_a_wrong_ticker_literal_is_counted_separately_from_a_wrong_name():
    sqls = ["SELECT value FROM v_revenue WHERE ticker = 'BRK-A' AND fiscal_year = 2024"]
    out = N.classify(rec(sqls, [True]), ["Berkshire Hathaway"], "BRK.B", DB)
    assert out["empty_with_wrong_ticker"] == 1 and out["empty_with_wrong_name"] == 0
    assert not out["all_empties_wrong_name"]


def test_perfect_linking_rewrites_every_name_predicate_to_the_cases_ticker_and_reruns():
    sqls = [
        "SELECT value FROM v_revenue WHERE name = 'The Coca-Cola Company' ORDER BY fiscal_year DESC LIMIT 1"
    ]
    out = N.classify(rec(sqls, [True]), ["Coca-Cola Company (The)"], "KO", DB)
    assert out["linked_with_rows"] == 1  # now it returns the Coca-Cola row


def test_an_empty_that_linking_cannot_fix_stays_empty():
    # JPMorgan has no v_revenue rows: a correct abstain, whatever the spelling
    sqls = ["SELECT value FROM v_revenue WHERE name = 'JPMorgan Chase & Co.' LIMIT 1"]
    out = N.classify(rec(sqls, [True]), ["JPMorgan Chase"], "JPM", DB)
    assert out["empty_with_wrong_name"] == 1 and out["linked_with_rows"] == 0


def test_the_audit_runs_over_a_run_file_and_summarises_nodata_abstains(tmp_path):
    case = {"id": "U07", "expected": "ANSWER_WITH_ASSUMPTION",
            "gold_sql": "SELECT value FROM v_revenue WHERE ticker='KO' ORDER BY fiscal_year DESC LIMIT 1"}  # fmt: skip
    sqls = ["SELECT value FROM v_revenue WHERE name = 'The Coca-Cola Company' LIMIT 1"] * 5
    run = tmp_path / "run.jsonl"
    run.write_text(json.dumps(rec(sqls, [True] * 5)) + "\n")
    out = N.audit(run, {"U07": case}, DB)
    assert out["nodata_abstains"] == 1 and out["all_empties_wrong_name"] == ["U07"]
