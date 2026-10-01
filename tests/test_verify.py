from ledgerql import verify


def test_extract_numbers_handles_plain_integer():
    assert verify.extract_numbers("The value is 391035000000.") == [391035000000.0]


def test_extract_numbers_handles_billions_word():
    assert verify.extract_numbers("Revenue was $391.0 billion.") == [391000000000.0]


def test_extract_numbers_excludes_plausible_years():
    assert verify.extract_numbers("This is fiscal year 2024 data.") == []


def test_extract_numbers_excludes_sec_form_codes():
    assert verify.extract_numbers("It filed a 10-K and a 10-Q.") == []


def test_extract_numbers_handles_negative_number():
    assert verify.extract_numbers("Revenue declined by -5.2%.") == [-5.2]


def test_extract_years_finds_bare_years():
    assert verify.extract_years("Revenue in fiscal year 2024 was strong.") == [2024]


def test_extract_years_ignores_non_year_numbers():
    assert verify.extract_years("Revenue was 391035000000.") == []


def test_extract_years_ignores_years_embedded_in_larger_numbers():
    # "2024000" contains the digits "2024" but is not itself a year.
    assert verify.extract_years("The raw value was 2024000.") == []


def test_extract_years_finds_multiple_years():
    assert verify.extract_years("Between fiscal 2023 and fiscal 2024.") == [2023, 2024]


def test_verify_passes_when_every_number_is_grounded():
    result = verify.verify(
        "The value was $391.0 billion.",
        ["ticker", "value"],
        [("AAPL", 391035000000.0)],
    )
    assert result.ok is True
    assert result.ungrounded_numbers == []


def test_verify_fails_on_ungrounded_number():
    result = verify.verify(
        "The value was $999.0 billion.",
        ["ticker", "value"],
        [("AAPL", 391035000000.0)],
    )
    assert result.ok is False
    assert result.ungrounded_numbers == [999000000000.0]
    assert "999000000000.0" in result.detail


def test_verify_fails_on_wrong_fiscal_year():
    result = verify.verify(
        "The fiscal 2025 revenue was $391.0 billion.",
        ["fiscal_year", "value"],
        [(2024, 391035000000.0)],
    )
    assert result.ok is False
    assert 2025.0 in result.ungrounded_numbers


def test_verify_passes_correct_fiscal_year():
    result = verify.verify(
        "The fiscal 2024 revenue was $391.0 billion.",
        ["fiscal_year", "value"],
        [(2024, 391035000000.0)],
    )
    assert result.ok is True


def test_verify_rejects_a_year_that_neither_the_result_nor_the_sql_contains():
    # The writer never sees the question, so a period it states that appears in
    # neither the rows nor the executed SQL was invented. (30B, L02: "fiscal year
    # 2022" over a bare value for a question about fiscal 2025.)
    result = verify.verify(
        "The value is 416,161,000,000.0 for fiscal year 2022.",
        ["value"],
        [(416161000000.0,)],
        sql="SELECT value FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year = 2025",
    )
    assert result.ok is False
    assert result.ungrounded_numbers == [2022.0]


def test_verify_rejects_an_unsupported_year_when_no_sql_is_given():
    assert verify.verify("As of 2024, the value was 5.0.", ["value"], [(5.0,)]).ok is False


def test_verify_grounds_a_year_in_the_sql_filter():
    sql = "SELECT value FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year = 2025"
    result = verify.verify("Revenue for fiscal year 2025 was 5.0.", ["value"], [(5.0,)], sql=sql)
    assert result.ok is True


def test_verify_grounds_a_year_in_a_date_literal_in_the_sql():
    sql = "SELECT value FROM v_cash WHERE period_end_date = '2024-09-28'"
    assert verify.verify("At the end of 2024 it was 5.0.", ["value"], [(5.0,)], sql=sql).ok is True


def test_verify_grounds_a_year_in_a_result_cell_that_is_not_a_fiscal_year_column():
    for cell in (2024, 2024.0, "2024-09-28"):
        result = verify.verify("In 2024 the value was 5.0.", ["value", "d"], [(5.0, cell)])
        assert result.ok is True, cell


def test_verify_does_not_ground_a_year_from_a_digit_run_in_a_larger_number():
    sql = "SELECT value FROM t WHERE cik = 20240000"
    assert verify.verify("In 2024 the value was 5.0.", ["value"], [(5.0,)], sql=sql).ok is False


def test_verify_keeps_the_stricter_fiscal_year_column_check_when_that_column_exists():
    # With a fiscal_year column the prose year must be one of ITS values; the
    # SQL literal does not rescue a year the column contradicts.
    result = verify.verify(
        "Fiscal 2025 revenue was 5.0.",
        ["fiscal_year", "value"],
        [(2024, 5.0)],
        sql="SELECT fiscal_year, value FROM v_revenue WHERE fiscal_year IN (2024, 2025)",
    )
    assert result.ok is False


def test_verify_passes_on_empty_result_with_no_claimed_numbers():
    result = verify.verify("No matching data was found.", ["value"], [])
    assert result.ok is True


def test_verify_passes_when_query_prescaled_the_value_to_billions():
    # A real gold-set query pattern: `SELECT value / 1e9 AS
    # revenue_in_billions ...` -- the grounded row value is already in
    # billions (391.035), and a correct answer restating it with a
    # matching magnitude word must not be rejected just because
    # extract_numbers() scales "391.035 billion" back up to
    # 391035000000.0 for comparison.
    result = verify.verify(
        "The revenue was $391.035 billion.",
        ["revenue_in_billions"],
        [(391.035,)],
    )
    assert result.ok is True


def test_verify_passes_when_query_prescaled_the_value_to_millions():
    result = verify.verify(
        "The revenue was $47941 million.",
        ["revenue_millions"],
        [(47941.0,)],
    )
    assert result.ok is True


def test_verify_still_rejects_a_genuinely_wrong_prescaled_number():
    # The scale-widening must not turn verification into a no-op --
    # a number that doesn't match at any scale is still ungrounded.
    result = verify.verify(
        "The revenue was $999.0 billion.",
        ["revenue_in_billions"],
        [(391.035,)],
    )
    assert result.ok is False


def test_verify_rejects_wrong_magnitude_word_against_scale_named_column():
    # Scale-widening for a `revenue_in_billions` column must only add the
    # one matching (billion) factor -- claiming "trillion" against the
    # same raw value must still be rejected, not silently accepted via
    # some other factor's widened value.
    result = verify.verify(
        "The revenue was $391.035 trillion.",
        ["revenue_in_billions"],
        [(391.035,)],
    )
    assert result.ok is False


def test_verify_rejects_wrong_magnitude_word_against_billions_column_as_millions():
    result = verify.verify(
        "The revenue was $391.035 million.",
        ["revenue_in_billions"],
        [(391.035,)],
    )
    assert result.ok is False


def test_verify_does_not_widen_a_column_whose_name_has_no_scale_word():
    # A blanket (unscoped) widening bug would have made *any* small
    # number ground a claim at any magnitude, regardless of column name.
    # A column named plainly (no "thousand"/"million"/"billion"/
    # "trillion" substring) must never be widened.
    result = verify.verify(
        "There were 5 billion.",
        ["n"],
        [(5,)],
    )
    assert result.ok is False


def test_years_and_day_labels_the_framing_states_are_grounded_only_when_the_caller_names_them():
    from ledgerql.verify import verify

    text = "Fiscal year 2025 (period ended June 30, 2025) was used."
    assert not verify(text, ["value"], [(1.0,)], sql="SELECT value FROM v_revenue").ok
    ok = verify(
        text,
        ["value"],
        [(1.0,)],
        sql="SELECT value FROM v_revenue",
        context_years={2025},
        context_numbers={30},
    )
    assert ok.ok
    # a year the framing did not say it stated is still caught, and so is a day it did not name
    assert not verify("Fiscal year 2024 was used.", ["value"], [(1.0,)], context_years={2025}).ok
    assert not verify(
        "It ended on June 29, 2025.",
        ["value"],
        [(1.0,)],
        context_years={2025},
        context_numbers={30},
    ).ok
