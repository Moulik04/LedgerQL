import duckdb
import pytest

from evals import entity_upper_bound as E

DB = "tests/fixtures/eval_fixture.duckdb"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(DB, read_only=True, config={"enable_external_access": "false"})
    yield c
    c.close()


def test_case_companies_come_from_gold_ticker_literals_and_name_searches(con):
    assert E.case_companies("SELECT 1 FROM v_revenue WHERE ticker='AAPL'", con) == [
        ("AAPL", "Apple Inc.")
    ]
    both = E.case_companies("... ticker IN ('AAPL','MSFT') ...", con)
    assert [t for t, _ in both] == ["AAPL", "MSFT"]
    ko = E.case_companies("SELECT ticker FROM companies WHERE name ILIKE '%coca-cola%'", con)
    assert ko == [("KO", "Coca-Cola Company (The)")]
    assert E.case_companies("SELECT COUNT(*) FROM companies", con) == []


@pytest.mark.parametrize(
    "literal,stored,expected",
    [
        ("The Coca-Cola Company", "Coca-Cola Company (The)", True),
        ("Microsoft Corporation", "Microsoft", True),
        ("Pfizer Inc.", "Pfizer", True),
        ("tesla", "Tesla, Inc.", True),
        ("Apple", "Apple Inc.", True),
        ("Amazon.com, Inc.", "Amazon", True),
        ("Microsoft", "Apple Inc.", False),
        ("Technology", "Apple Inc.", False),
    ],
)
def test_a_name_literal_is_linked_to_the_company_it_refers_to(literal, stored, expected):
    assert E.same_company(literal, stored) is expected


def test_rewrite_turns_name_predicates_into_ticker_predicates(con):
    companies = [("KO", "Coca-Cola Company (The)")]
    out = E.rewrite_name_predicates(
        "SELECT ticker FROM companies WHERE name = 'The Coca-Cola Company'", companies
    )
    assert "ticker = 'KO'" in out and "name" not in out.lower().replace("ticker", "")
    assert con.execute(out).fetchall() == [("KO",)]


def test_rewrite_handles_like_ilike_lower_in_and_qualified_columns():
    companies = [("MSFT", "Microsoft"), ("PFE", "Pfizer")]
    sql = (
        "SELECT 1 FROM companies c WHERE c.name ILIKE '%microsoft%' OR LOWER(name) LIKE '%pfizer%' "
        "OR name IN ('Microsoft Corporation', 'Pfizer Inc.')"
    )
    out = E.rewrite_name_predicates(sql, companies)
    assert out.count("ticker") == 3  # one ticker predicate per name predicate: c.ticker, ticker, IN
    assert "'MSFT'" in out and "'PFE'" in out
    assert "c.ticker" in out


def test_rewrite_leaves_other_predicates_and_unmatched_literals_alone():
    companies = [("AAPL", "Apple Inc.")]
    sql = "SELECT 1 FROM companies WHERE gics_sector = 'Technology' AND name = 'Nvidia'"
    assert E.rewrite_name_predicates(sql, companies) == sql
    assert E.rewrite_name_predicates("not sql at all (", companies) == "not sql at all ("
    assert E.rewrite_name_predicates("SELECT 1", []) == "SELECT 1"


def test_rewrite_is_idempotent():
    companies = [("AAPL", "Apple Inc.")]
    once = E.rewrite_name_predicates("SELECT 1 FROM companies WHERE name = 'Apple'", companies)
    assert E.rewrite_name_predicates(once, companies) == once
