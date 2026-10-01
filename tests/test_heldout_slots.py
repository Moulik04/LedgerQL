from collections import Counter

import duckdb
import pytest

from evals import heldout_slots as H

DB = "tests/fixtures/eval_fixture.duckdb"


@pytest.fixture(scope="module")
def companies():
    con = duckdb.connect(DB, read_only=True, config={"enable_external_access": "false"})
    rows = con.execute("SELECT cik, ticker, name FROM companies ORDER BY cik").fetchall()
    con.close()
    return rows


def test_the_template_counts_sum_to_fifty_and_keep_the_dev_sets_behaviour_mix():
    rows = H.template_rows("A")
    assert len(rows) == 50
    by_expected = Counter(r["expected"] for r in rows)
    assert by_expected == {"ANSWER": 24, "ANSWER_WITH_ASSUMPTION": 10, "ABSTAIN": 16}
    by_tier = Counter(r["tier"] for r in rows)
    assert set(by_tier) == set(H.DEV_TIER_MIX)  # every dev tier is present
    assert [r["id"] for r in rows] == [f"H{i:02d}" for i in range(1, 51)]


def test_the_larger_variant_has_eighty_rows_and_the_same_tiers():
    rows = H.template_rows("B")
    assert len(rows) == 80 and set(r["tier"] for r in rows) == set(H.DEV_TIER_MIX)


def test_entity_classes_are_computed_from_the_name_alone():
    assert H.entity_class("Apple Inc.", "AAPL") == "plain"
    assert H.entity_class("Coca-Cola Company (The)", "KO") == "inverted_the"
    assert H.entity_class("AT&T", "T") == "punctuated"
    assert H.entity_class("Alphabet Inc. (Class A)", "GOOGL") == "share_class"
    assert H.entity_class("Berkshire Hathaway", "BRK.B") == "multi_word"


def test_assignment_is_deterministic_for_a_seed_and_differs_across_seeds(companies):
    a = H.assign(H.template_rows("A"), companies, dev_tickers=set(), seed=1)
    b = H.assign(H.template_rows("A"), companies, dev_tickers=set(), seed=1)
    c = H.assign(H.template_rows("A"), companies, dev_tickers=set(), seed=2)
    assert a == b and a != c


def test_no_company_is_used_twice_and_dev_companies_are_excluded(companies):
    dev = {"AAPL", "MSFT", "KO", "TSLA", "META"}
    rows = H.assign(H.template_rows("A"), companies, dev_tickers=dev, seed=7)
    used = [s["ticker"] for r in rows for s in r["company_slots"]]
    assert len(used) == len(set(used)) == H.total_slots("A")
    assert not dev & set(used)


def test_every_slot_carries_a_class_and_a_mention_style_and_no_question_text(companies):
    rows = H.assign(H.template_rows("A"), companies, dev_tickers=set(), seed=3)
    styles = {s["mention_style"] for r in rows for s in r["company_slots"]}
    assert styles == set(H.MENTION_STYLES)
    for r in rows:
        assert r["question"] is None
        for s in r["company_slots"]:
            assert s["class"] in H.ENTITY_CLASSES and s["name"] and s["ticker"]
    classes = Counter(s["class"] for r in rows for s in r["company_slots"])
    assert len(classes) >= 4  # the draw is stratified, not dominated by plain names


def test_the_committed_template_is_the_eighty_question_variant_with_no_questions_yet():
    committed = H.load_template()
    assert len(committed) == 80 and committed[-1]["id"] == "H80"
    assert Counter(r["expected"] for r in committed) == {
        "ANSWER": 40,
        "ANSWER_WITH_ASSUMPTION": 16,
        "ABSTAIN": 24,
    }
    assert all(r["question"] is None for r in committed) or H.questions_written()
    assert sum(r["n_slots"] for r in committed) == H.total_slots("B")
    assert all(len(r["company_slots"]) == r["n_slots"] for r in committed)


def test_the_assignment_is_pinned_by_a_hash_written_with_the_template():
    assert (
        H.assignment_digest(H.load_template()) == H.HASH_PATH.read_text().split()[0]
    ), "the company assignment is committed before any question is written and must not change"


def test_the_human_readable_sheet_is_what_the_committed_template_renders_to():
    assert H.SHEET_PATH.read_text() == H.render_sheet(H.load_template())
    sheet = H.SHEET_PATH.read_text()
    assert "H80" in sheet and "mention style" in sheet.lower()
