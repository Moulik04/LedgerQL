from ledgerql.result_shape import is_identity_anchored_empty


def test_empty_result_with_ticker_equality_is_anchored():
    sql = "SELECT value FROM v_revenue WHERE ticker = 'NVDA' AND fiscal_year = 2025"
    assert is_identity_anchored_empty(sql, []) is True


def test_empty_result_with_name_equality_is_anchored():
    sql = "SELECT value FROM v_revenue WHERE name = 'Acme Rockets Inc' AND fiscal_year = 2024"
    assert is_identity_anchored_empty(sql, []) is True


def test_all_null_single_row_counts_as_empty():
    # T05's real shape: an aggregate CAGR calc over an unmatched fiscal
    # year returns one row of NULL, not zero rows.
    sql = (
        "SELECT (POWER((MAX(CASE WHEN fiscal_year = 2025 THEN value END) / "
        "MAX(CASE WHEN fiscal_year = 2022 THEN value END)), (1.0/3.0)) - 1) * 100 "
        "AS cagr FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year IN (2022, 2025)"
    )
    assert is_identity_anchored_empty(sql, [(None,)]) is True


def test_identity_equality_inside_a_subquery_is_anchored():
    sql = (
        "SELECT fiscal_period FROM filings WHERE cik = "
        "(SELECT cik FROM companies WHERE ticker = 'TSLA') AND form = '8-K' "
        "ORDER BY filed_date DESC LIMIT 1"
    )
    assert is_identity_anchored_empty(sql, []) is True


def test_set_query_with_no_identity_filter_is_not_anchored():
    # G06's real shape: "which companies had negative total assets" --
    # empty is itself a correct answer, must NOT be flagged.
    sql = "SELECT name, value FROM v_total_assets WHERE fiscal_year=2024 AND value<0"
    assert is_identity_anchored_empty(sql, []) is False


def test_join_condition_plus_a_real_filter_is_still_anchored():
    # v.cik = c.cik is a join condition, not itself an anchor (the other
    # side is a Column, not a literal/subquery) -- but the separate
    # `c.name = 'X'` filter still anchors this query, and the join
    # condition must not suppress that.
    sql = (
        "SELECT c.name, v.value FROM companies c LEFT JOIN v_revenue v "
        "ON v.cik=c.cik AND v.fiscal_year=2024 WHERE c.name = 'X'"
    )
    assert is_identity_anchored_empty(sql, []) is True


def test_pure_join_with_no_literal_identity_filter_is_not_anchored():
    sql = "SELECT c.name, v.value FROM companies c LEFT JOIN v_revenue v ON v.cik=c.cik"
    assert is_identity_anchored_empty(sql, []) is False


def test_like_and_ilike_on_identity_column_are_anchored():
    assert (
        is_identity_anchored_empty("SELECT cik FROM companies WHERE name LIKE '%Amazon%'", [])
        is True
    )
    assert (
        is_identity_anchored_empty("SELECT cik FROM companies WHERE name ILIKE '%berkshire%'", [])
        is True
    )


def test_nonempty_result_is_never_flagged_regardless_of_sql():
    sql = "SELECT value FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year = 2024"
    assert is_identity_anchored_empty(sql, [(391035000000.0,)]) is False


def test_none_sql_is_not_anchored():
    assert is_identity_anchored_empty(None, []) is False


def test_unparseable_sql_fails_closed_not_anchored():
    assert is_identity_anchored_empty("not valid sql (((", []) is False


def test_survivors_unanimously_empty_requires_every_survivor_empty_or_null():
    from ledgerql.result_shape import survivors_unanimously_empty

    assert survivors_unanimously_empty([[], []]) is True
    assert survivors_unanimously_empty([[], [(None,)]]) is True
    assert survivors_unanimously_empty([[], [(1,)]]) is False


def test_survivors_unanimously_empty_is_false_with_no_survivors():
    # No candidate executed at all is consensus.py's EXEC_ERROR path, not
    # an empty-result signal -- all([]) being True must not leak through.
    from ledgerql.result_shape import survivors_unanimously_empty

    assert survivors_unanimously_empty([]) is False


def test_entity_bound_no_data_needs_both_unanimity_and_an_entity_anchor():
    from ledgerql.result_shape import is_entity_bound_no_data

    anchored = "SELECT value FROM v_revenue WHERE ticker = 'NVDA' AND fiscal_year = 2025"
    set_query = "SELECT name FROM v_total_assets WHERE fiscal_year = 2024 AND value < 0"
    assert is_entity_bound_no_data(anchored, [[], []]) is True
    assert is_entity_bound_no_data(anchored, [[], [(1,)]]) is False
    assert is_entity_bound_no_data(set_query, [[], []]) is False


import pytest  # noqa: E402

from ledgerql.result_shape import is_tautologically_empty  # noqa: E402


@pytest.mark.parametrize(
    "sql",
    [
        # The two real 30B generations for H03 and O07: the generator refusing in SQL.
        "SELECT NULL AS credit_rating WHERE 1 = 0",
        "SELECT NULL AS customer_satisfaction_score WHERE FALSE",
        "SELECT v FROM v_revenue WHERE 1 <> 1",
        "SELECT v FROM v_revenue WHERE 'a' = 'b'",
        "SELECT v FROM v_revenue WHERE NOT TRUE",
        "SELECT v FROM v_revenue WHERE ticker = 'AAPL' AND FALSE",
        "SELECT v FROM v_revenue WHERE (1 = 2) OR (3 < 2)",
        "SELECT v FROM v_revenue WHERE NULL",
        "SELECT NULL AS x",
    ],
)
def test_constant_false_or_constant_null_queries_are_tautologically_empty(sql):
    assert is_tautologically_empty(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT value FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year = 2024",
        "SELECT v FROM v_revenue WHERE 1 = 1",
        "SELECT v FROM v_revenue WHERE ticker = 'AAPL' OR FALSE",
        "SELECT 1 AS one",
        # Real H05: returns a real 0 over a real table -- not tautological.
        "SELECT COUNT(*) FROM financial_facts WHERE tag = 'NumberOfStores'",
        # A NULL projection over a real table with a real filter is not constant-empty.
        "SELECT NULL AS x FROM v_revenue WHERE ticker = 'AAPL'",
        "SELECT v FROM t WHERE 1 = 'a'",  # mixed types: unknown, not false
        "not valid sql (((",
        None,
    ],
)
def test_ordinary_queries_are_not_tautologically_empty(sql):
    assert is_tautologically_empty(sql) is False


def test_multiple_statements_are_not_judged():
    assert is_tautologically_empty("SELECT NULL WHERE FALSE; SELECT 1") is False
