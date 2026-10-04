"""The comparison harness's findings, pinned: the verifier and the independent audit on planted
values and on correct restatements (`evals/audit_vs_verify.py`). They agree on every row since the
verifier was fixed on 2026-10-03; if either changes and a row stops agreeing, this fails."""

import duckdb
import pytest

from evals import audit_vs_verify as A


def test_the_auditor_catches_every_planted_invented_value():
    missed = [p["form"] for p in A.plant_table() if not p["audit_catches"]]
    assert missed == []


def test_the_verifier_catches_every_planted_invented_value():
    # Until 2026-10-03 it missed seven: a figure inside its 1% tolerance (three forms), every
    # spelled-out number (three forms), and a form-code lookalike.
    missed = [p["form"] for p in A.plant_table() if not p["verifier_catches"]]
    assert missed == []


def test_the_auditor_accepts_every_correct_restatement_but_a_coarse_rounding_is_weak_not_clean():
    refused = [h["form"] for h in A.honest_table() if not h["audit_accepts"]]
    assert refused == []


def test_the_verifier_accepts_every_correct_restatement():
    # Until 2026-10-03 it refused five: `$416B`, `416 bn`, `$0.4T`, `FY25` and `3rd`.
    refused = [h["form"] for h in A.honest_table() if not h["verifier_accepts"]]
    assert refused == []


# --- blocked drafts: is a block an invented number, or the verifier being wrong? ---------------

_SQL = "SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2025"


def _blocked(i, draft):
    rec = {"id": i, "answer": None, "reason_code": "UNGROUNDED_ANSWER", "columns": ["value"],
           "rows": [[416161000000.0]], "generated_sql": _SQL}  # fmt: skip
    if draft is not None:
        rec["blocked_draft"] = draft
    return rec


_RECORDS = [
    _blocked("invented", "Revenue was $999 billion."),
    _blocked("true", "Revenue was $416 billion."),  # a true statement: the block was wrong
    _blocked("coarse", "Revenue was about 400 billion."),  # weak tier: reported, not invented
    _blocked("old", None),  # a run from before drafts were stored
    {
        "id": "shipped",
        "answer": "Revenue was 416,161,000,000.0.",
        "reason_code": None,
        "columns": ["value"],
        "rows": [[416161000000.0]],
        "generated_sql": _SQL,
    },  # fmt: skip
    {"id": "abstained", "answer": None, "reason_code": "LOW_AGREEMENT"},
]


def test_each_blocked_draft_is_an_invention_or_a_verifier_false_positive():
    blocks = {b["id"]: b for b in A.classify_blocks(_RECORDS, None)}
    assert set(blocks) == {"invented", "true", "coarse", "old"}  # only what the verifier blocked
    assert blocks["invented"]["verdict"] == "invented"
    assert blocks["invented"]["ungrounded"] == [("number", "$999 billion")]
    assert blocks["true"]["verdict"] == "verifier false positive"
    assert blocks["coarse"]["verdict"] == "verifier false positive"
    assert blocks["coarse"]["weak"]  # and its weak claim is listed, never merged
    assert blocks["old"]["verdict"] == "draft not stored"


def test_the_draft_rate_counts_blocks_and_splits_them():
    assert A.draft_rate(_RECORDS, None) == {
        "drafted": 5,
        "shipped": 1,
        "blocked": 4,
        "invented": 1,
        "verifier_false_positive": 2,
        "unresolved": 0,
        "draft_not_stored": 1,
    }


# --- unresolved: the auditor cannot tell which company, so it gives no verdict ------------------

_PATTERN_SQL = "SELECT value FROM v_revenue WHERE name LIKE '%Apple%'"


@pytest.fixture()
def db(tmp_path):
    """Apple has fiscal 2025 only; fiscal 2024 is 3M's."""
    path = tmp_path / "t.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE companies(cik INT, ticker VARCHAR, name VARCHAR)")
    con.execute("INSERT INTO companies VALUES (1,'MMM','3M'), (2,'AAPL','Apple Inc.')")
    con.execute(
        "CREATE TABLE filings(adsh VARCHAR, cik INT, fiscal_year INT, period_end_date DATE)"
    )
    con.execute("INSERT INTO filings VALUES ('a',1,2024,'2024-12-31'), ('b',2,2025,'2025-09-27')")
    con.execute("CREATE TABLE financial_facts(cik INT, ddate DATE)")
    con.close()
    return str(path)


def _unresolved_records():
    year_only = {**_blocked("cannot-tell", "Revenue was $416 billion in fiscal 2024."),
                 "generated_sql": _PATTERN_SQL}  # fmt: skip
    both = {**_blocked("invented-too", "Revenue was $999 billion in fiscal 2024."),
            "generated_sql": _PATTERN_SQL}  # fmt: skip
    return [year_only, both, _blocked("true", "Revenue was $416 billion.")]


def test_a_block_the_auditor_cannot_resolve_is_neither_invented_nor_a_false_positive(db):
    blocks = {b["id"]: b for b in A.classify_blocks(_unresolved_records(), db)}
    assert blocks["cannot-tell"]["verdict"] == "unresolved"
    assert blocks["cannot-tell"]["unresolved"] == [("year", "2024")]
    assert blocks["cannot-tell"]["ungrounded"] == []
    # an ungrounded claim beside it decides the block: invented, with the unresolved one listed
    assert blocks["invented-too"]["verdict"] == "invented"
    assert blocks["invented-too"]["unresolved"] == [("year", "2024")]
    assert blocks["true"]["verdict"] == "verifier false positive"


def test_the_draft_rate_counts_unresolved_blocks_on_their_own(db):
    rate = A.draft_rate(_unresolved_records(), db)
    assert (rate["blocked"], rate["invented"], rate["verifier_false_positive"]) == (3, 1, 1)
    assert rate["unresolved"] == 1


def test_the_report_prints_unresolved_claims_separately_and_not_as_disagreements(db):
    records = _unresolved_records()
    row = {"run": "r", "id": "S1", "answer": "Revenue was $416 billion in fiscal 2024.",
           "columns": ["value"], "rows": [[416161000000.0]], "sql": _PATTERN_SQL,
           "verifier_ok": True, "audit_clean": True, "ungrounded": [], "weak": [], "derived": [],
           "unresolved": [("year", "2024")], "claims": 2}  # fmt: skip
    blocks = {"r": {"rate": A.draft_rate(records, db), "blocks": A.classify_blocks(records, db)}}
    text = A.render([row], {"r": 1}, [], [], blocks)
    assert "| run | answered | auditor flags | unresolved | weak | derived |" in text
    assert "| r | 1 | 0 | 1 | 0 | 0 |" in text
    assert "Disagreements: 0 of 1 answered records." in text
    assert "## Unresolved claims in shipped answers: 1" in text and "### r / S1" in text
    assert "| run | drafted | blocked | invented | verifier false positive | unresolved |" in text
    assert "### r / cannot-tell: unresolved" in text
