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


def test_verify_ignores_fiscal_year_check_when_column_absent():
    # No fiscal_year column in this result -- a stated year (however
    # implausible) is not something this function can ground, so it
    # must not be flagged.
    result = verify.verify(
        "As of 2024, the value was 5.0.",
        ["value"],
        [(5.0,)],
    )
    assert result.ok is True


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
