# ruff: noqa: E501  (questions, SQL and expected sentences are single lines)
"""frame_answer: the deterministic framing sentence(s) that state what an answer assumed
(ledgerql/frame.py). It sees the question, the winning SQL and the result's shape, never a value;
every numeral in it is a year or date label taken from the SQL, the question or the database."""

import inspect
import json
import re

import duckdb
import pytest

from ledgerql import frame as F

DB = "tests/fixtures/eval_fixture.duckdb"
GOLD = {c["id"]: c for c in (json.loads(x) for x in open("evals/gold.jsonl"))}


def frame(case_id, **kw):
    case = GOLD[case_id]
    return F.frame_answer(
        case["question"], case["gold_sql"], F.ResultShape([], 1), db_path=DB, **kw
    )


def db_one(sql):
    con = duckdb.connect(DB, read_only=True)
    try:
        return con.execute(sql).fetchone()
    finally:
        con.close()


def test_the_framing_is_given_the_shape_of_the_result_and_no_values():
    params = inspect.signature(F.frame_answer).parameters
    assert list(params)[:3] == ["question", "sql", "result_shape"]
    assert not {"rows", "values", "result"} & set(params)
    assert set(inspect.signature(F.ResultShape).parameters) == {"columns", "row_count"}


@pytest.mark.parametrize("case_id,view,ticker", [("L03", "v_net_income", "MSFT"),
                                                 ("L04", "v_total_assets", "NVDA"),
                                                 ("L09", "v_cash", "XOM")])  # fmt: skip
def test_a_most_recent_period_is_resolved_from_the_database_and_stated_as_an_assumption(
    case_id, view, ticker
):
    fy, end = db_one(
        f"SELECT fiscal_year, period_end_date FROM {view} WHERE ticker='{ticker}' ORDER BY fiscal_year DESC LIMIT 1"
    )
    f = frame(case_id)
    assert f.assumed
    assert f"fiscal year {fy}" in f.text.lower()
    assert (
        end.strftime("%B") in f.text and str(end.year) in f.text
    )  # the period end date, spelled out
    assert fy in f.years and end.year in f.years


def test_an_explicit_fiscal_year_that_the_sql_uses_is_not_an_assumption():
    f = frame("L01")  # "What was Apple's revenue in fiscal year 2024?"
    assert not f.assumed and f.text == ""


def test_a_bare_year_read_as_a_fiscal_year_is_stated_with_when_it_ended():
    end = db_one("SELECT period_end_date FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2024")[
        0
    ]
    f = frame("U02")  # "What was Apple's revenue for 2024?"
    assert f.assumed
    assert "2024 was read as fiscal year 2024" in f.text
    assert end.strftime("%B") in f.text


def test_no_period_in_the_question_means_the_latest_on_record_is_stated():
    fy = db_one("SELECT max(fiscal_year) FROM v_revenue WHERE ticker='AAPL'")[0]
    f = frame("M01")  # "What is Apple's revenue?"
    assert f.assumed and f"fiscal year {fy}" in f.text.lower() and "most recent" in f.text.lower()


def test_a_ranking_with_no_stated_metric_says_which_metric_it_used():
    f = frame("M02")  # "Which is the biggest company in the database?"
    assert f.assumed
    assert "'Biggest' was measured by revenue" in f.text
    assert "fiscal year" in f.text.lower()


def test_a_colloquial_term_is_stated_as_the_concept_the_query_used():
    f = frame("M06")  # "What was Amazon's profit in fiscal year 2024?" over v_net_income
    assert f.assumed and "'Profit' was interpreted as net income" in f.text


def test_a_brand_name_that_resolved_to_a_different_stored_name_is_stated():
    f = frame("M08")  # "What was Google's revenue in fiscal year 2024?"
    assert f.assumed and "'Google' was resolved to Alphabet" in f.text and "GOOGL" in f.text


def test_a_stated_scale_is_restated_without_naming_a_currency_and_the_raw_unit_is_looked_up():
    assert "billions" in frame("U01").text.lower()
    assert "dollars" not in frame("U05").text.lower()  # U05 counts shares, not dollars
    assert "millions" in frame("U07").text.lower()
    u08 = frame("U08").text  # "...and in what unit is the raw value stored?"
    assert "base USD" in u08 and "not thousands or millions" in u08


def test_a_sum_over_years_names_the_years_it_summed():
    f = frame("C06")  # "...summed across every fiscal year on record?"
    years = sorted(
        r[0]
        for r in duckdb.connect(DB, read_only=True)
        .execute("SELECT fiscal_year FROM v_net_income WHERE ticker='TSLA'")
        .fetchall()
    )
    assert f.assumed and all(str(y) in f.text for y in years)


def test_a_balance_asked_for_across_years_is_not_summed_and_says_so():
    f = frame("U03")  # "...total assets across fiscal years 2024 and 2025 combined?"
    assert f.assumed and "point-in-time" in f.text and "not added together" in f.text


def test_two_companies_most_recent_years_and_that_fiscal_years_end_at_different_times():
    f = frame("G05")
    assert f.assumed and "Amazon" in f.text and "Walmart" in f.text
    assert "different" in f.text and "calendar" in f.text


def test_every_numeral_in_the_framing_comes_from_the_question_the_sql_or_a_database_label():
    for cid in (
        "L03",
        "L04",
        "L09",
        "U01",
        "U02",
        "U07",
        "M01",
        "M02",
        "M06",
        "M08",
        "G05",
        "C06",
        "U03",
    ):
        f = frame(cid)
        source = GOLD[cid]["question"] + " " + GOLD[cid]["gold_sql"]
        for n in re.findall(r"\d+", f.text):
            assert n in source or int(n) in f.years or int(n) in f.numbers, (cid, n, f.text)


def test_the_framing_states_no_value_from_the_result():
    con = duckdb.connect(DB, read_only=True)
    for cid in ("L03", "M01", "U02", "G05", "C06"):
        values = [
            v
            for row in con.execute(GOLD[cid]["gold_sql"]).fetchall()
            for v in row
            if isinstance(v, float)
        ]
        text = frame(cid).text.replace(",", "")
        for v in values:
            assert str(int(v)) not in text and f"{v:.1f}" not in text
    con.close()


def test_a_missing_database_yields_only_what_the_sql_and_question_support():
    f = F.frame_answer(
        "What was Apple's revenue in 2024?",
        GOLD["U02"]["gold_sql"],
        F.ResultShape([], 1),
        db_path="/nonexistent.duckdb",
    )
    assert "2024 was read as fiscal year 2024" in f.text  # from the question and the SQL alone
    f = F.frame_answer(
        GOLD["L03"]["question"],
        GOLD["L03"]["gold_sql"],
        F.ResultShape([], 1),
        db_path="/nonexistent.duckdb",
    )
    assert f.text == ""  # the latest year cannot be named without the database


def test_a_query_the_framer_cannot_parse_gets_no_framing_not_a_crash():
    f = F.frame_answer("q", "this is not sql (", F.ResultShape([], 0), db_path=DB)
    assert f.text == "" and not f.assumed


def test_a_ranking_by_an_aggregate_of_value_under_an_alias_still_says_which_metric_and_which_years():
    sql = (
        "SELECT c.name, c.ticker, MAX(f.value) AS max_value FROM companies AS c "
        "JOIN v_total_assets AS f ON c.cik = f.cik GROUP BY c.name, c.ticker "
        "ORDER BY max_value DESC LIMIT 1"
    )
    f = F.frame_answer(
        "Which is the biggest company in the database?", sql, F.ResultShape([], 1), db_path=DB
    )
    assert f.assumed
    assert "'Biggest' was measured by total assets" in f.text
    assert "All fiscal years on record were considered." in f.text


def test_a_ranking_that_names_its_metric_adds_no_metric_clause():
    sql = "SELECT name FROM v_revenue WHERE fiscal_year=2024 ORDER BY value DESC LIMIT 10"
    f = F.frame_answer(
        "Which 10 companies had the highest revenue in fiscal year 2024?",
        sql,
        F.ResultShape([], 10),
        db_path=DB,
    )
    assert "measured by" not in f.text
