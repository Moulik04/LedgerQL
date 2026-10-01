# ruff: noqa: E501  (test questions and expected sentences are single lines)
"""Deterministic abstain explanations (ledgerql/refusal.py): no model in the path, one template per
reason code, a known-gaps registry anchored to docs/schema.md, and no invented numbers."""

import json
import re
from pathlib import Path

import pytest

from ledgerql import refusal as R

DB = "tests/fixtures/eval_fixture.duckdb"


def text(code, question):
    return R.explain(code, question, db_path=DB).text


def test_every_reason_code_has_a_template_and_the_set_matches_the_documented_codes():
    assert set(R.TEMPLATES) == set(R.REASON_CODES)
    readme = Path("evals/README.md").read_text()
    for code in R.REASON_CODES:
        assert code in readme  # the documented abstain codes (evals/README.md section 2)
        assert R.explain(code, "anything at all", db_path=DB).text  # never empty


def test_an_unknown_reason_code_is_an_error_not_a_silent_blank():
    with pytest.raises(ValueError, match="reason code"):
        R.explain("MADE_UP", "q", db_path=DB)


def test_no_data_names_the_company_and_the_period_from_the_question_and_the_linker():
    out = text("NO_DATA", "What was Tesla's revenue in fiscal year 2030?")
    assert out == "No 10-K in this database covers Tesla, Inc. for fiscal year 2030."
    assert text("NO_DATA", "What was Tesla's revenue?").startswith("No 10-K in this database has")
    assert "matches this question" in text("NO_DATA", "How many unicorns are there?")


def test_the_gap_registry_is_anchored_to_the_schema_document():
    schema = re.sub(r"[`*]", "", " ".join(Path("docs/schema.md").read_text().split()))
    for gap in R.load_gaps():
        quote = re.sub(r"[`*]", "", " ".join(gap["source_quote"].split()))
        assert quote in schema, f"{gap['id']}: its quote is not in docs/schema.md"
        assert gap["source"] == "docs/schema.md"


def test_a_bank_without_a_revenue_tag_gets_the_documented_gap_not_a_generic_no_data():
    for q in ("What was JPMorgan's revenue in fiscal year 2024?",
              "What was JPMorgan's net profit margin in fiscal year 2024?"):  # fmt: skip
        out = R.explain("NO_DATA", q, db_path=DB)
        assert out.gap == "no_revenue_tag"
        assert "JPMorgan Chase" in out.text and "bank holding companies" in out.text
        assert "revenue" in out.text and "cannot be computed" in out.text


def test_the_revenue_gap_needs_a_revenue_question_and_a_company_that_really_lacks_the_rows():
    assert (
        R.explain(
            "NO_DATA", "What was JPMorgan's total assets in fiscal year 2024?", db_path=DB
        ).gap
        is None
    )
    assert (
        R.explain("NO_DATA", "What was Apple's revenue in fiscal year 2031?", db_path=DB).gap
        is None
    )


def test_each_documented_gap_fires_on_its_own_question_and_states_the_documented_fact():
    cases = {
        "no_dimensional_breakdowns": ("Break down Apple's fiscal 2024 revenue by geographic region.", "geographic breakdowns"),
        "annual_only": ("What was Apple's revenue in the second quarter of fiscal year 2025?", "annual"),
        "staging_tables": ("Show me the contents of the stg_num staging table.", "debugging"),
        "headcount": ("How many employees did Tesla have at the end of fiscal year 2024?", "employee"),
        "no_8k_filings": ("Which fiscal period does Tesla's most recent 8-K filing correspond to?", "8-K"),
        "dual_class_ticker": ("What was GOOG's revenue in fiscal year 2024?", "GOOGL"),
    }  # fmt: skip
    for gap_id, (question, must) in cases.items():
        out = R.explain("NO_DATA", question, db_path=DB)
        assert out.gap == gap_id, (gap_id, out)
        assert must.lower() in out.text.lower(), (gap_id, out.text)


def test_the_8k_text_is_derived_from_the_data_for_that_company():
    out = R.explain(
        "NO_DATA", "Which fiscal period does Tesla's most recent 8-K correspond to?", db_path=DB
    )
    assert "Tesla, Inc." in out.text and "10-K" in out.text and "10-Q" in out.text


def test_a_company_that_does_have_8k_filings_does_not_get_the_no_8k_text():
    import duckdb

    con = duckdb.connect(DB, read_only=True)
    ticker = con.execute(
        "SELECT c.ticker FROM companies c JOIN filings f ON f.cik = c.cik WHERE f.form = '8-K' LIMIT 1"
    ).fetchone()[0]
    con.close()
    out = R.explain("NO_DATA", f"What was the most recent 8-K for {ticker}?", db_path=DB)
    assert out.gap != "no_8k_filings"


def test_no_template_can_emit_a_number_that_is_not_in_the_question_or_the_linker_output():
    allowed_words = ("10-K", "10-Q", "8-K", "S&P 500")
    questions = [json.loads(line)["question"] for line in open("evals/gold.jsonl")]
    from ledgerql.entity_link import EntityLinker

    linker = EntityLinker.from_db(DB)
    for q in questions:
        links = " ".join(f"{k.name} {k.ticker}" for k in linker.link(q))
        source = q + " " + links
        for code in R.REASON_CODES:
            out = R.explain(code, q, db_path=DB).text
            stripped = out
            for w in allowed_words:
                stripped = stripped.replace(w, "")
            for number in re.findall(r"\d[\d,.]*", stripped):
                assert number.rstrip(".,") in source, (code, q, number, out)


def test_the_refusal_path_has_no_model_in_it():
    source = Path("ledgerql/refusal.py").read_text()
    for forbidden in ("ollama", "llm_backends", "generate", "classify", "httpx", "requests"):
        assert not re.search(rf"^\s*(import|from)\s+.*{forbidden}", source, re.M), forbidden


def test_a_missing_database_degrades_to_the_generic_text_rather_than_failing():
    out = R.explain(
        "NO_DATA", "What was JPMorgan's revenue in fiscal year 2024?", db_path="/nonexistent.duckdb"
    )
    assert out.text and out.gap is None
