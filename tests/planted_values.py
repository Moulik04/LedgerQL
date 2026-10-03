"""The planted-value suite shared by the independent auditor (`evals/number_audit.py`) and the
pipeline's verifier (`ledgerql/verify.py`).

The true value in every text is 416,161,000,000 (Apple, fiscal year 2025). Each INVENTED text
states a value, year, date or label that is not in the result and must be flagged; each HONEST
text restates a true fact in some form and must not be. Both implementations are tested against
these same lists, and neither implementation's code is the other's: if one of them needs a new
form, add it here and both fail until both handle it.
"""

COLUMNS = ["ticker", "fiscal_year", "value"]
ROWS = [("AAPL", 2025, 416161000000.0)]
SQL = (
    "SELECT ticker, fiscal_year, value FROM v_revenue WHERE ticker = 'AAPL' AND fiscal_year = 2025"
)

INVENTED = [
    # digits, decimals, thousands separators, currency
    "Revenue was 417,500,000,000.0.",
    "Revenue was 417500000000.",
    "Revenue was $417,500,000,000.",
    "Revenue was 4.17 trillion dollars.",
    # magnitude words and abbreviations
    "Revenue was $417.5 billion.",
    "Revenue was 417.5 bn.",
    "Revenue was 417.5bn.",
    "Revenue was $417.5B.",
    "Revenue was 0.45T.",
    "Revenue was 417,500 million.",
    "Revenue was 417,500,000 thousand.",
    "Revenue was 417500K.",
    # mis-scaled: right digits, wrong unit
    "Revenue was 416.161 million.",
    "Revenue was 416.161 trillion.",
    "Revenue was 416,161 thousand.",
    # a round number with no hedge states its zeros: 416.161 billion is not 420 or 400 billion
    "Revenue was 420 billion.",
    "Revenue was $400B.",
    "Revenue was four hundred billion.",
    # percentages
    "Growth was 38%.",
    "Growth was 38 percent.",
    "Growth was 38 per cent.",
    "It rose 2.5 percentage points.",
    # spelled out
    "Revenue was four hundred seventeen billion.",
    "Revenue was twelve billion.",
    "There were forty-two.",
    "That is thirty eight percent.",
    "Revenue was two point five trillion.",
    "Revenue was one hundred twenty-three million.",
    "Revenue was three hundred and five thousand.",
    "About a hundred.",
    "Roughly a billion dollars.",
    # years, dates, labels
    "For fiscal year 2022.",
    "For FY22.",
    "As of 2023.",
    "The period ended June 30, 2022.",
    "The period ended 30 June 2022.",
    "The period ended 2022-06-30.",
    "The period ended 6/30/2022.",
    "In June 2022.",
    "In the quarter Q2.",
]


HONEST = [
    "Revenue was 416,161,000,000.0.",
    "Revenue was 416161000000.",
    "Revenue was $416.161 billion.",
    "Revenue was about 416 billion.",
    "Revenue was 416.2 billion.",
    # hedged, a round number is a rounding to its last non-zero place
    "Revenue was roughly 420 billion.",
    "Revenue was about four hundred billion.",
    "Revenue was ~$420B.",
    "Revenue was $416B.",
    "Revenue was 416 bn.",
    "Revenue was 0.4T.",
    "Revenue was 416,161 million.",
    "Revenue was 416161000 thousand.",
    "Revenue was four hundred sixteen billion.",
    "Revenue was four hundred sixteen billion one hundred sixty-one million.",
    "For fiscal year 2025.",
    "For FY25.",
    "There was one row for the one company.",
    "The 10-K for fiscal 2025, not a 5th filing; see H2O and x86.",
    "Between the 1st and the 3rd.",
]
