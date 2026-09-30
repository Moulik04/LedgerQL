import json
from pathlib import Path

import pytest

from ledgerql.entity_link import EntityLinker, hint_for, name_tokens, same_company

COMPANIES = [
    (320193, "AAPL", "Apple Inc."),
    (789019, "MSFT", "Microsoft"),
    (21344, "KO", "Coca-Cola Company (The)"),
    (34088, "XOM", "ExxonMobil"),
    (19617, "JPM", "JPMorgan Chase"),
    (1326801, "META", "Meta Platforms"),
    (1018724, "AMZN", "Amazon"),
    (1652044, "GOOGL", "Alphabet Inc. (Class A)"),
    (1067983, "BRK.B", "Berkshire Hathaway"),
    (1045810, "NVDA", "Nvidia"),
    (6951, "AMAT", "Applied Materials"),
    (1097149, "ON", "ON Semiconductor"),
    (4962, "AXP", "American Express"),
    (5272, "AIG", "American International Group"),
]


@pytest.fixture(scope="module")
def linker():
    return EntityLinker(COMPANIES)


def tickers(links):
    return [link.ticker for link in links]


def test_name_tokens_drop_legal_forms_and_articles():
    assert name_tokens("Coca-Cola Company (The)") == {"coca", "cola"}
    assert name_tokens("Amazon.com, Inc.") == {"amazon"}
    assert same_company("The Coca-Cola Company", "Coca-Cola Company (The)")
    assert not same_company("Apple", "Applied Materials")


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What was Apple's revenue in fiscal year 2024?", ["AAPL"]),
        ("What is The Coca-Cola Company's ticker symbol?", ["KO"]),
        ("Compare Apple's and Microsoft's net margins for fiscal year 2024", ["AAPL", "MSFT"]),
        ("What was Exxon Mobil's cash balance in its most recent fiscal year?", ["XOM"]),
        ("What is JPMorgan's registrant name exactly as filed with the SEC?", ["JPM"]),
        ("On what date did Meta file its most recent 10-K?", ["META"]),
        ("How much larger was Amazon's revenue than Walmart's?", ["AMZN"]),
        ("What was Google's revenue in fiscal year 2024?", ["GOOGL"]),
        ("What was Berkshire Hathaway's revenue in fiscal year 2024?", ["BRK.B"]),
        ("What were NVIDIA's total assets?", ["NVDA"]),
        ("What was the revenue of NVDA in 2024?", ["NVDA"]),
    ],
)
def test_links_the_companies_a_question_names(linker, question, expected):
    assert tickers(linker.link(question)) == expected


@pytest.mark.parametrize(
    "question",
    [
        "Which companies reported revenue above $300 billion in any fiscal year on record?",
        "What percentage of companies in the database appear at all in the revenue view?",
        "Which GICS sector had the highest average net income in fiscal year 2024?",
        "How many companies are classified under the Information Technology sector?",
        "On what date was the last filing made?",
        "What was the revenue of Acme Rockets Inc in fiscal year 2024?",
        "American companies with high margins",  # ambiguous prefix: American Express / AIG
    ],
)
def test_links_nothing_when_no_company_is_named_or_the_name_is_ambiguous(linker, question):
    assert linker.link(question) == []


def test_a_link_carries_the_mention_the_stored_name_and_how_it_matched(linker):
    (link,) = linker.link("What is The Coca-Cola Company's ticker symbol?")
    assert (link.ticker, link.name, link.cik) == ("KO", "Coca-Cola Company (The)", 21344)
    assert link.mention.lower().startswith("the coca-cola") or "Coca-Cola" in link.mention
    assert link.how == "name"
    assert linker.link("What was NVDA revenue?")[0].how == "ticker"


def test_a_company_named_twice_is_linked_once(linker):
    assert tickers(linker.link("Apple's revenue versus Apple Inc.'s net income")) == ["AAPL"]


def test_hint_states_the_stored_spelling_and_is_empty_without_links(linker):
    hint = hint_for("What is The Coca-Cola Company's ticker symbol?", linker)
    assert "ticker = 'KO'" in hint and "Coca-Cola Company (The)" in hint
    assert hint.startswith("Companies named in the question")
    assert hint_for("How many companies are in the database?", linker) == ""


def test_no_false_links_on_the_gold_questions_that_name_no_company():
    """Over the real mart: every gold question is linked to at most the companies its own gold
    SQL names, and never to one it does not (a false link would mislead the model)."""
    import duckdb

    from evals.entity_upper_bound import case_companies

    con = duckdb.connect(
        "tests/fixtures/eval_fixture.duckdb",
        read_only=True,
        config={"enable_external_access": "false"},
    )
    linker = EntityLinker.from_connection(con)
    false_links = {}
    for line in Path("evals/gold.jsonl").read_text().splitlines():
        case = json.loads(line)
        named = {t for t, _ in case_companies(case.get("gold_sql"), con)}
        extra = [t for t in tickers(linker.link(case["question"])) if t not in named]
        if extra and case["expected"] in ("ANSWER", "ANSWER_WITH_ASSUMPTION"):
            false_links[case["id"]] = extra
    con.close()
    assert false_links == {}
