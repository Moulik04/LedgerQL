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
