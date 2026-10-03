"""Replaying two verifiers on one run's drafts (`evals/replay_verifier.py`)."""

from evals import replay_verifier as R
from ledgerql import verify

SQL = "SELECT value FROM v_revenue WHERE ticker='AAPL' AND fiscal_year=2025"


def _rec(i, text, shipped):
    rec = {"id": i, "columns": ["value"], "rows": [[416161000000.0]], "generated_sql": SQL,
           "answer": text if shipped else None,
           "reason_code": None if shipped else "UNGROUNDED_ANSWER"}  # fmt: skip
    if not shipped:
        rec["blocked_draft"] = text
    return rec


RECORDS = [
    _rec("exact", "Revenue was 416,161,000,000.0.", True),
    _rec("abbrev", "Revenue was $416B.", True),  # true; the verifier before the change refused it
    _rec("off", "Revenue was $417.5 billion.", False),  # invented; it used to pass (inside 1%)
    _rec("wild", "Revenue was $999 billion.", False),  # invented; blocked by both
    {"id": "abstained", "answer": None, "reason_code": "LOW_AGREEMENT"},
    {"id": "old-block", "answer": None, "reason_code": "UNGROUNDED_ANSWER"},  # no draft stored
]


def _strict_on_abbreviations(answer, columns, rows, sql=None, **kw):
    """A stand-in for the verifier before 2026-10-03: no abbreviations, a flat 1% tolerance."""
    if "416B" in answer:
        return verify.VerifyResult(ok=False, detail="unsupported: [416.0]")
    if "417.5" in answer:
        return verify.VerifyResult(ok=True)
    return verify.verify(answer, columns, rows, sql=sql, **kw)


def _replayed():
    return R.replay(RECORDS, {"old": _strict_on_abbreviations, "new": verify.verify}, {}, None)


def test_every_draft_is_replayed_shipped_or_blocked_and_an_unstored_block_is_named():
    rows, not_stored = _replayed()
    assert [r["id"] for r in rows] == ["exact", "abbrev", "off", "wild"]
    assert not_stored == ["old-block"]


def test_the_summary_separates_false_abstains_from_inventions_on_each_side():
    rows, _ = _replayed()
    assert R.summarize(rows, "old") == {
        "drafted": 4, "blocked": 2, "blocked_invented": 1, "false_abstains": 1,
        "shipped": 2, "shipped_flagged": 1, "shipped_weak": 0, "shipped_derived": 0,
    }  # fmt: skip
    assert R.summarize(rows, "new") == {
        "drafted": 4, "blocked": 2, "blocked_invented": 2, "false_abstains": 0,
        "shipped": 2, "shipped_flagged": 0, "shipped_weak": 0, "shipped_derived": 0,
    }  # fmt: skip


def test_the_drafts_whose_verdict_changed_are_listed_with_both_verdicts():
    rows, not_stored = _replayed()
    assert [r["id"] for r in R.changed(rows, "old", "new")] == ["abbrev", "off"]
    text = R.render(rows, not_stored, "old", "new", "x.jsonl")
    assert "### abbrev: blocked -> shipped" in text and "### off: shipped -> blocked" in text
    assert "### wild: invented" in text and "old-block" in text


def test_the_verifier_of_an_earlier_revision_can_be_loaded_beside_the_current_one():
    head = R.load_verifier("HEAD")
    assert head.verify is not verify.verify
    assert head.verify("The value is 5.0.", ["v"], [(5.0,)]).ok
