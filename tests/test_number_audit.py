import ast
import datetime as dt
from pathlib import Path

import duckdb
import pytest

from evals import number_audit as N
from tests.planted_values import COLUMNS, HONEST, INVENTED, ROWS, SQL


def audit(text, columns=COLUMNS, rows=ROWS, sql=SQL, db_path=None):
    return N.audit_answer(text, columns, rows, sql, db_path)


def bad(text, **kw):
    return [c.text for c in audit(text, **kw).ungrounded]


# --- independence -----------------------------------------------------------------------------


def test_the_auditor_imports_nothing_from_ledgerql_and_nothing_that_does():
    tree = ast.parse(Path(N.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            imported |= {a.name for a in node.names if node.module in ("evals", None)}
    assert "ledgerql" not in imported
    assert not imported & {"evals", "verify", "year_audit"}
    assert (
        "verify" not in Path(N.__file__).read_text().split('"""', 2)[2].lower().split("import")[0]
    )


# --- planted invented values, every form ------------------------------------------------------


@pytest.mark.parametrize("text", INVENTED)
def test_a_planted_invented_value_is_flagged(text):
    assert bad(text), text


# --- the same facts, correctly restated, in every form, are not flagged -----------------------


@pytest.mark.parametrize("text", HONEST)
def test_a_correct_restatement_is_not_flagged(text):
    assert bad(text) == [], text


def test_rounding_is_judged_at_the_precision_the_claim_states():
    # 416.161 billion: four hundred sixteen is its rounding, 417 and 415 are not.
    assert bad("416 billion") == []
    assert bad("417 billion") == ["417 billion"]
    assert bad("416.2 billion") == []
    assert bad("416.3 billion") == ["416.3 billion"]
    # "four hundred billion" leaves its precision unstated: a coarse rounding, weak, never strong
    assert [c.status for c in audit("about four hundred billion").claims] == ["weak"]
    assert bad("about four hundred fifty billion") != []


def test_a_percentage_matches_a_ratio_cell_times_100_or_a_cell_already_in_percent():
    assert bad("It was 12.5%.", columns=["m"], rows=[(0.1253,)]) == []
    assert bad("It was 12.5%.", columns=["m"], rows=[(12.5,)]) == []
    assert bad("It was 13%.", columns=["m"], rows=[(0.1253,)]) == []  # 12.53 rounds to 13
    assert bad("It was 14%.", columns=["m"], rows=[(0.1253,)]) == ["14%"]


def test_a_column_that_names_its_scale_grounds_the_scaled_figure():
    cols, rows = ["revenue_in_billions"], [(416.161,)]
    assert bad("Revenue was $416.161 billion.", columns=cols, rows=rows) == []
    assert bad("Revenue was 416.161.", columns=cols, rows=rows) == []
    # with no scale in the name, 416.161 does not ground "billion"
    assert bad("Revenue was $416.161 billion.", columns=["value"], rows=rows) != []


def test_a_sign_is_ignored_when_matching_a_decrease():
    assert bad("Fell by 5.", columns=["chg"], rows=[(-5.0,)]) == []


def test_the_row_count_grounds_a_count_of_what_was_returned():
    rows = [(f"T{i}", float(i)) for i in range(10)]
    assert bad("The ten companies are listed.", columns=["a", "b"], rows=rows) == []
    assert bad("The 10 companies.", columns=["a", "b"], rows=rows) == []
    assert bad("The eleven companies.", columns=["a", "b"], rows=rows) != []  # 10 + 1 is no count


def test_a_number_equal_to_a_sum_or_difference_of_cells_is_derived_not_invented():
    rows = [(1000.0, 250.0)]
    a = audit("The gap is 750.", columns=["x", "y"], rows=rows)
    assert [c.status for c in a.claims] == ["derived"] and a.clean
    assert bad("The gap is 751.", columns=["x", "y"], rows=rows) == ["751"]
    assert bad("It is 4x.", columns=["x", "y"], rows=rows) == []  # glued: an identifier
    # fewer than three significant digits can never be "derived": too easy to match by accident
    assert bad("The gap is 60.", columns=["x", "y"], rows=[(100.0, 40.0)]) == ["60"]
    # the row count and a year cell are not operands
    assert bad("About a hundred.") == ["a hundred"]


def test_spelled_out_numbers_have_the_edge_cases_the_spec_states():
    assert bad("One of them.", rows=[()]) == []  # a bare "one" is a pronoun
    assert bad("There are two and five of them.", columns=["a"], rows=[(1,)]) == ["two", "five"]
    assert [c.value for c in audit("twenty-one thousand").claims] == [21000.0]
    assert [c.value for c in audit("a hundred").claims] == [100.0]
    assert [c.value for c in audit("two point five").claims] == [2.5]


def test_form_codes_are_labels_but_a_lookalike_is_a_number():
    assert audit("Filed a 10-K and a 10-Q and an 8-K.").claims == []
    assert bad("Filed a 5-K.") == ["5"]


def test_a_name_with_a_digit_in_the_result_or_database_is_not_a_magnitude():
    rows = [("3M", 5.0)]
    assert bad("3M had 5.", columns=["name", "n"], rows=rows) == []
    assert bad("3M Company had 5.", columns=["x", "n"], rows=[("a", 5.0)]) != []


def test_dates_are_one_claim_and_need_the_date_not_just_the_year():
    rows = [(dt.date(2025, 6, 30), 1.5)]
    cols = ["period_end", "v"]
    for t in ("June 30, 2025", "30 June 2025", "2025-06-30", "6/30/2025", "Jun. 30 2025"):
        a = audit(f"Period ended {t}.", columns=cols, rows=rows, sql="")
        assert [c.kind for c in a.claims] == ["date"] and a.clean, t
    assert bad("Period ended June 29, 2025.", columns=cols, rows=rows, sql="") == ["June 29, 2025"]
    assert bad("In June 2025.", columns=cols, rows=rows, sql="") == []
    assert bad("In June 2024.", columns=cols, rows=rows, sql="") == ["June 2024"]
    assert bad("On June 30.", columns=cols, rows=rows, sql="") == []


def test_a_year_in_the_sql_filter_grounds_the_period_but_other_sql_numbers_do_not():
    assert bad("For fiscal year 2025.", columns=["value"], rows=[(1.5,)], sql=SQL) == []
    assert bad("There were 10.", columns=["value"], rows=[(1.5,)], sql="SELECT 1 LIMIT 10") != []


def test_a_quarter_label_needs_to_be_in_the_result_or_sql():
    assert bad("In Q3.", columns=["p"], rows=[("Q3",)]) == []
    assert bad("In Q3.") == ["Q3"]


# --- the database: weak grounding for labels ---------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE companies(cik INT, ticker VARCHAR, name VARCHAR)")
    con.execute("INSERT INTO companies VALUES (1,'MMM','3M'), (2,'AAPL','Apple Inc.')")
    con.execute(
        "CREATE TABLE filings(adsh VARCHAR, cik INT, fiscal_year INT, period_end_date DATE)"
    )
    con.execute("INSERT INTO filings VALUES ('a',1,2024,'2024-12-31'), ('b',2,2025,'2025-09-27')")
    con.execute("CREATE TABLE financial_facts(cik INT, ddate DATE)")
    con.execute("INSERT INTO financial_facts VALUES (2,'2025-09-27')")
    con.close()
    N.load_db_labels.cache_clear()
    return str(path)


def test_a_label_found_only_in_the_database_is_weak_not_strong_and_not_ungrounded(db):
    a = audit("For fiscal year 2024.", columns=["value"], rows=[(1.5,)], sql="", db_path=db)
    assert [(c.status, c.source) for c in a.claims] == [("weak", "database label")]
    assert a.clean
    assert bad("For fiscal year 2022.", columns=["value"], rows=[(1.5,)], sql="", db_path=db)
    d = audit("Ended September 27, 2025.", columns=["v"], rows=[(1.5,)], sql="", db_path=db)
    assert [c.status for c in d.claims] == ["weak"]
    assert bad("Ended September 28, 2025.", columns=["v"], rows=[(1.5,)], sql="", db_path=db)


def test_numbers_get_no_weak_grounding_and_database_names_with_digits_are_masked(db):
    assert bad("There were 2,025 widgets.", columns=["v"], rows=[(1.5,)], sql="", db_path=db) != []
    assert bad("3M had 1.5.", columns=["v"], rows=[(1.5,)], sql="", db_path=db) == []


def test_a_label_the_named_company_has_is_grounded_and_one_only_another_company_has_is_weak(db):
    aapl = "SELECT v FROM t WHERE ticker = 'AAPL'"
    mmm = "SELECT v FROM t WHERE ticker = 'MMM'"
    text = "Fiscal year 2025, ended September 27, 2025."
    own = N.audit_answer(text, ["v"], [(1.5,)], aapl, db)
    assert [(c.status, c.source) for c in own.claims] == [
        ("grounded", "database, for the company the SQL names")
    ] * 2
    other = N.audit_answer(text, ["v"], [(1.5,)], mmm, db)
    assert [c.status for c in other.claims] == ["weak", "weak"]  # real labels, wrong company
    assert N.audit_answer(text, ["v"], [(1.5,)], "SELECT 1", db).clean  # names none: weak, clean


def test_coarse_rounding_is_its_own_tier_never_ungrounded_and_never_strong():
    for text in ("roughly 420 billion", "about 400 billion", "420,000,000,000"):
        a = audit(text)
        assert [c.status for c in a.claims] == ["weak"], text
        assert a.claims[0].source.startswith("coarse rounding")
    # below ten, or off by more than the unstated precision, there is no such reading
    for text in ("about 4 billion", "about 450 billion", "about 417 billion", "750"):
        assert bad(text), text


def test_a_spelled_out_number_is_judged_at_the_scale_word_it_ends_on():
    assert bad("four hundred sixteen billion") == []
    assert bad("four hundred seventeen billion") == ["four hundred seventeen billion"]
