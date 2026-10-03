"""The comparison harness's findings, pinned: the verifier and the independent audit on planted
values and on correct restatements (`evals/audit_vs_verify.py`). They agree on every row since the
verifier was fixed on 2026-10-03; if either changes and a row stops agreeing, this fails."""

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
        "draft_not_stored": 1,
    }
