"""The verifier against the shared planted-value suite (`tests/planted_values.py`), plus the forms
the independent audit found it got wrong (`reports/number_audit_vs_verify.md`): a true statement
it refused, and an invented one it accepted."""

import datetime as dt

import pytest

from ledgerql import verify
from tests.planted_values import COLUMNS, HONEST, INVENTED, ROWS, SQL


def check(text, columns=COLUMNS, rows=ROWS, sql=SQL, **kw):
    return verify.verify(text, columns, rows, sql=sql, **kw)


def flagged(text, *args, **kw):
    return not check(text, *args, **kw).ok


@pytest.mark.parametrize("text", INVENTED)
def test_a_planted_invented_value_is_blocked(text):
    assert flagged(text), text


@pytest.mark.parametrize("text", HONEST)
def test_a_correct_restatement_is_not_blocked(text):
    result = check(text)
    assert result.ok, (text, result.detail)


# --- too strict: true values in other forms ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Revenue was $416B.", "Revenue was 416 bn.", "Revenue was $0.4T.", "Revenue was 416.2bn."],
)
def test_magnitude_abbreviations_are_magnitudes(text):
    assert not flagged(text), text


@pytest.mark.parametrize("text", ["For FY25.", "For FY2025.", "In fiscal 2025."])
def test_a_fiscal_year_label_is_a_year_not_a_number(text):
    assert not flagged(text), text


def test_a_fiscal_year_label_is_still_checked_as_a_year():
    assert flagged("For FY22.")
    assert flagged("For FY2022.")


@pytest.mark.parametrize("text", ["Between the 1st and the 3rd.", "It was the 2nd and 21st."])
def test_ordinals_are_not_claims(text):
    assert not flagged(text), text


def test_a_list_marker_is_not_a_claim():
    # one row, so neither 2 nor 3 could be grounded as a value or a count
    text = "Results:\n1. Apple\n2. Microsoft\n3) Tesla"
    assert not flagged(text, ["n"], [("Apple",)], sql="")
    assert flagged("There are 2. Apple", ["n"], [("Apple",)], sql="")  # mid-line: a number


def test_an_identifier_with_digits_glued_to_letters_is_not_a_claim():
    assert not flagged("See H2O and x86 and COVID19.")


def test_a_name_with_a_digit_in_the_result_is_not_a_claim():
    result = check("3M had 5 filings.", columns=["name", "n"], rows=[("3M", 5)], sql="")
    assert result.ok, result.detail


def test_a_ratio_cell_may_be_stated_as_a_percentage():
    # R02 (30B): return on assets 0.17208..., stated as "17.2%"; the verifier refused it.
    assert not flagged("The return on assets was 17.2%.", ["roa"], [(0.17208583985957596,)], sql="")
    assert not flagged("It was 17.2 percent.", ["roa"], [(0.17208583985957596,)], sql="")
    assert flagged("It was 17.3%.", ["roa"], [(0.17208583985957596,)], sql="")
    # but a ratio cell is not a plain 17.2, and a percentage-looking cell is not scaled up
    assert flagged("The value was 17.2.", ["roa"], [(0.17208583985957596,)], sql="")
    assert flagged("It was 1,720.8%.", ["roa"], [(0.17208583985957596,)], sql="")


def test_the_row_count_grounds_a_plain_count_not_a_scaled_one():
    # no cell is near 10, so only the number of rows could ground it
    rows = [(f"T{i}", float(i) * 1000 + 0.25) for i in range(10)]
    cols = ["a", "b"]
    assert not flagged("The 10 companies.", cols, rows, sql="")
    assert not flagged("The ten companies.", cols, rows, sql="")
    assert flagged("The eleven companies.", cols, rows, sql="")
    assert flagged("10 billion companies.", cols, rows, sql="")
    assert flagged("10%.", cols, rows, sql="")


# --- too lenient: invented values it used to accept ---------------------------------------------


def test_a_stated_figure_must_agree_to_the_precision_it_states():
    # true value 416.161 billion
    assert not flagged("416 billion")
    assert flagged("417 billion")
    assert not flagged("416.2 billion")
    assert flagged("416.3 billion")  # 0.03% off: inside the old 1% tolerance
    assert flagged("$417.5 billion")  # 0.3% off
    assert flagged("417,500,000,000.0")
    assert not flagged("416,161,000,000.0")
    assert flagged("416,161,000,001.0")  # states one decimal, so it must be that exact


@pytest.mark.parametrize(
    "text",
    [
        "about 420 billion",
        "About 400 billion",
        "approximately $420 billion",
        "roughly 420 bn",
        "around $420B",
        "nearly 420 billion",
        "~420 billion",
        "~ $420 billion",
        "about four hundred billion",
        "roughly four hundred twenty billion",
    ],
)
def test_a_hedged_whole_number_may_be_a_rounding_to_its_last_non_zero_place(text):
    # true value 416.161 billion: 420 is its rounding to two figures, 400 to one
    assert not flagged(text), text


@pytest.mark.parametrize(
    "text",
    [
        "420 billion",  # no hedge: the zero is a stated digit, and 416.161 is not 420
        "Revenue was 420 billion.",
        "$400B",
        "four hundred billion",
        "Revenue was exactly 420 billion.",
        "about the same: 420 billion",  # the hedge must be on the figure itself
        "about 450 billion",  # hedged, but not a rounding of 416.161 at any place
        "roughly four hundred fifty billion",
        "about 4 billion",  # below 100 there is only the one reading
    ],
)
def test_unhedged_trailing_zeros_are_significant(text):
    assert flagged(text), text


def test_a_hedge_does_not_loosen_a_figure_that_states_its_precision():
    assert not flagged("about 416 billion")
    assert flagged("about 417 billion")
    assert flagged("about 416.3 billion")
    # and an exact whole number needs no hedge
    assert not flagged("Revenue was 416,161,000,000.")
    assert not flagged("416161000000")


def test_a_scale_named_column_grounds_the_scaled_figure_at_its_precision():
    cols, rows = ["revenue_in_billions"], [(416.161,)]
    assert not flagged("Revenue was $416.161 billion.", cols, rows, sql="")
    assert not flagged("Revenue was $416.2 billion.", cols, rows, sql="")
    assert flagged("Revenue was $416.3 billion.", cols, rows, sql="")
    assert flagged("Revenue was $416.161 million.", cols, rows, sql="")


@pytest.mark.parametrize(
    "text",
    [
        "There were forty-two.",
        "Revenue was four hundred seventeen billion.",
        "That is thirty eight percent.",
        "About a hundred.",
        "Roughly a billion dollars.",
        "Revenue was two point five trillion.",
    ],
)
def test_a_spelled_out_number_is_read_and_checked(text):
    assert flagged(text), text


def test_spelled_out_numbers_that_are_true_pass_and_the_edge_cases_hold():
    assert not flagged("Revenue was four hundred sixteen billion.")
    assert not flagged("One of them.")  # a bare "one" is a pronoun
    assert flagged("There are two and five of them.", ["a"], [(1,)], sql="")  # two numbers
    assert [c.value for c in verify.extract_claims("twenty-one thousand")] == [21000.0]
    assert [c.value for c in verify.extract_claims("a hundred")] == [100.0]
    assert [c.value for c in verify.extract_claims("two point five")] == [2.5]
    assert [c.value for c in verify.extract_claims("three hundred and five thousand")] == [305000.0]


def test_a_lookalike_form_code_is_a_number_and_a_real_one_is_not():
    assert not flagged("Filed a 10-K, a 10-Q, an 8-K and a 10-K/A.")
    assert flagged("Filed a 391-K.")
    assert flagged("Filed a 5-K.")


# --- the period labels and dates the old code could not see or could not read -------------------


def test_a_quarter_or_half_label_must_be_in_the_result_or_the_sql():
    assert flagged("In Q3.")
    assert not flagged("In Q3.", ["p"], [("Q3",)], sql="")
    assert not flagged("In H2 of the year.", ["p"], [("h2",)], sql="")
    assert flagged("In H2 of the year.", ["p"], [("Q3",)], sql="")


def test_a_date_stated_in_words_is_grounded_by_a_date_in_the_result():
    # L07 (30B): the result held '2026-01-29'; the day "29" was refused as an unsupported number.
    rows, cols = [("2026-01-29",)], ["filed_date"]
    assert not flagged("It was filed on January 29, 2026.", cols, rows, sql="")
    assert not flagged("It was filed on 29 January 2026.", cols, rows, sql="")
    assert not flagged("It was filed on 2026-01-29.", cols, rows, sql="")
    assert not flagged("It was filed on Jan. 29, 2026.", cols, rows, sql="")
    assert flagged("It was filed on January 28, 2026.", cols, rows, sql="")
    assert flagged("It was filed on February 29, 2026.", cols, rows, sql="")
    assert flagged("It was filed on 2026-01-28.", cols, rows, sql="")
    assert not flagged("It was filed on January 29.", cols, rows, sql="")


def test_a_date_object_in_the_result_grounds_a_date():
    rows, cols = [(dt.date(2025, 6, 30), 1.5)], ["period_end", "v"]
    assert not flagged("Period ended June 30, 2025, value 1.5.", cols, rows, sql="")
    assert flagged("Period ended June 29, 2025, value 1.5.", cols, rows, sql="")
    assert not flagged("Period ended 6/30/2025, value 1.5.", cols, rows, sql="")


def test_a_date_literal_in_the_sql_grounds_a_date():
    sql = "SELECT value FROM t WHERE period_end_date = '2024-09-28'"
    assert not flagged("As of September 28, 2024 it was 5.0.", ["value"], [(5.0,)], sql=sql)
    assert flagged("As of September 27, 2024 it was 5.0.", ["value"], [(5.0,)], sql=sql)


def test_the_framings_day_label_still_grounds_only_the_day_it_named():
    text = "Fiscal year 2025 (period ended June 30, 2025) was used."
    assert flagged(text, ["value"], [(1.0,)], sql="SELECT value FROM v_revenue")
    ok = check(text, ["value"], [(1.0,)], sql="SELECT value FROM v_revenue",
               context_years={2025}, context_numbers={30})  # fmt: skip
    assert ok.ok, ok.detail
    assert flagged("It ended on June 29, 2025.", ["value"], [(1.0,)], context_years={2025},
                   context_numbers={30})  # fmt: skip


def test_a_date_range_or_hyphenated_pair_is_not_a_negative_number():
    rows = [(2024, 1), (2025, 2)]
    assert not flagged("Between 2024-2025 values rose.", ["fiscal_year", "v"], rows, sql="")


# --- identifiers: an accession number is one string, not three quantities (H3, 2026-10-04) -----

ADSH = "0000037996-26-000015"


def test_an_accession_number_the_result_holds_is_not_three_numbers():
    # L11 (30B, job 47412929): the result was this one cell, the draft quoted it, and the three
    # digit groups were refused as the numbers 37996, 26 and 15.
    text = (
        f"The data shows a single filing with accession number {ADSH}. There are no other "
        "values provided in the table to describe additional information about this filing."
    )
    result = check(text, ["adsh"], [(ADSH,)], sql="SELECT adsh FROM filings LIMIT 1")
    assert result.ok, result.detail


def test_an_identifier_is_one_claim_and_states_no_quantity():
    claims = verify.extract_claims(f"Filing {ADSH} was found.")
    assert [(c.kind, c.text) for c in claims] == [("identifier", ADSH)]
    assert verify.extract_numbers(f"Filing {ADSH} was found.") == []


def test_an_identifier_the_result_does_not_hold_is_refused_as_one_claim():
    result = check("The filing is 0000037996-26-000016.", ["adsh"], [(ADSH,)], sql="")
    assert not result.ok
    assert result.ungrounded_claims == ["0000037996-26-000016"]
    assert result.ungrounded_numbers == []


def test_an_identifier_is_grounded_by_the_exact_string_and_by_nothing_else():
    said = f"The filing is {ADSH}."
    # its digit groups as numbers in the result are not the string
    assert flagged(said, ["cik", "yy", "seq"], [(37996, 26, 15)], sql="")
    # the SQL is not the result
    assert flagged(said, ["form"], [("10-K",)], sql=f"SELECT form FROM f WHERE adsh = '{ADSH}'")
    # a piece of a longer identifier is not that identifier, with or without its leading zeros
    assert flagged("The filing is 0000037996-26-00001.", ["adsh"], [(ADSH,)], sql="")
    assert flagged("The filing is 37996-26-000015.", ["adsh"], [(ADSH,)], sql="")
    assert flagged("The filing is 37996-26-15.", ["adsh"], [(ADSH,)], sql="")
    # the whole string inside a longer cell is
    assert not flagged(said, ["path"], [(f"edgar/data/37996/{ADSH}.txt",)], sql="")
    assert not flagged(said, ["path"], [(f"{ADSH}-index.htm",)], sql="")


def test_each_identifier_in_a_list_is_checked_on_its_own():
    rows = [(ADSH,), ("0000320193-24-000123",)]
    assert not flagged(f"They are {ADSH} and 0000320193-24-000123.", ["adsh"], rows, sql="")
    result = check(f"They are {ADSH} and 0000320193-24-000124.", ["adsh"], rows, sql="")
    assert result.ungrounded_claims == ["0000320193-24-000124"]


def test_a_number_beside_a_grounded_identifier_is_still_checked():
    assert flagged(f"Filing {ADSH} reported 7 items.", ["adsh"], [(ADSH,)], sql="")
    assert flagged(f"Filing {ADSH} was for fiscal 2022.", ["adsh"], [(ADSH,)], sql="")


def test_a_year_shaped_group_inside_an_identifier_is_not_a_year():
    # with a fiscal_year column a stated year must be one of its values; the 2024 here is no year
    cols, rows = ["ref", "fiscal_year"], [("1234-2024-5678", 2025)]
    result = check("Reference 1234-2024-5678, fiscal year 2025.", cols, rows, sql="")
    assert result.ok, result.detail
    # and an identifier that is not there is reported once, not also as a year
    result = check("Reference 1234-2024-5679, fiscal year 2025.", cols, rows, sql="")
    assert result.ungrounded_claims == ["1234-2024-5679"] and result.ungrounded_numbers == []


def test_a_run_of_years_is_years_not_an_identifier():
    # "2023-2024-2025" is three years, each checked as a year, as it was before identifiers
    cols, rows = ["fiscal_year", "v"], [(2023, 1.0), (2024, 2.0), (2025, 3.0)]
    assert verify.extract_claims("Fiscal years 2023-2024-2025.") == []
    assert not flagged("Fiscal years 2023-2024-2025.", cols, rows, sql="")
    result = check("Fiscal years 2022-2023-2024.", cols, rows, sql="")
    assert result.ungrounded_claims == ["2022"]


def test_two_digit_groups_and_a_date_are_not_identifiers():
    # a range is two quantities, and an ISO date is a date
    assert [c.kind for c in verify.extract_claims("Between 10-15 filings.")] == ["number"] * 2
    assert flagged("Between 10-15 filings.", ["n"], [(10,)], sql="")
    assert [c.kind for c in verify.extract_claims("Filed 2026-01-29.")] == ["date"]
    assert not flagged("Filed 2026-01-29.", ["filed"], [("2026-01-29",)], sql="")
    assert flagged("Filed 2026-01-28.", ["filed"], [("2026-01-29",)], sql="")


# --- the result carries what was claimed, for the auditor -------------------------------------


def test_the_result_lists_every_claim_it_could_not_ground():
    r = check("Revenue was 417 billion, in Q2, for FY22.")
    assert not r.ok
    assert 417000000000.0 in r.ungrounded_numbers
    assert any("Q2" in c for c in r.ungrounded_claims)
    assert 2022.0 in r.ungrounded_numbers


def test_a_result_string_is_masked_only_as_a_whole_word_and_only_if_it_is_a_name():
    # a string cell "10" must not blank the "10" inside "510", leaving a "5" the result grounds
    assert flagged("There were 510 filings.", ["form", "n"], [("10", 5)], sql="")
    # a name made of a number word is not a claim where the answer repeats it
    rows = [("Five Below", 3.5)]
    assert not flagged("Five Below had 3.5.", ["name", "v"], rows, sql="")
    assert flagged("Five companies had 3.5.", ["name", "v"], rows, sql="")


def test_the_verifier_imports_nothing_from_the_evals():
    # the auditor must stay independent in both directions (see tests/test_number_audit.py)
    import ast
    from pathlib import Path

    tree = ast.parse(Path(verify.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"datetime", "re", "dataclasses", "decimal"}
