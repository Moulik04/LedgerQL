from pathlib import Path

from ledgerql.data.sp500 import SP500Company, load_sp500, sp500_ciks

FIXTURE = Path(__file__).parent / "fixtures" / "sp500_small.csv"


def test_load_sp500_parses_rows():
    companies = load_sp500(FIXTURE)
    assert companies == [
        SP500Company("AAPL", "Apple Inc.", 320193, "Information Technology"),
        SP500Company("MSFT", "Microsoft", 789019, "Information Technology"),
        SP500Company("AMZN", "Amazon", 1018724, "Consumer Discretionary"),
    ]


def test_sp500_ciks_returns_set_of_ints():
    companies = load_sp500(FIXTURE)
    assert sp500_ciks(companies) == {320193, 789019, 1018724}


def test_load_sp500_default_path_has_full_list():
    companies = load_sp500()
    assert len(companies) >= 490
    assert len(sp500_ciks(companies)) >= 490
    tickers = {c.ticker for c in companies}
    assert {"AAPL", "MSFT", "AMZN", "JPM"} <= tickers
