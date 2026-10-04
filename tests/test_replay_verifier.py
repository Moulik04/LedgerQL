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
        "drafted": 4, "blocked": 2, "blocked_invented": 1, "blocked_unresolved": 0,
        "false_abstains": 1, "shipped": 2, "shipped_flagged": 1, "shipped_unresolved": 0,
        "shipped_weak": 0, "shipped_derived": 0,
    }  # fmt: skip
    assert R.summarize(rows, "new") == {
        "drafted": 4, "blocked": 2, "blocked_invented": 2, "blocked_unresolved": 0,
        "false_abstains": 0, "shipped": 2, "shipped_flagged": 0, "shipped_unresolved": 0,
        "shipped_weak": 0, "shipped_derived": 0,
    }  # fmt: skip


def _row(i, ok, **tiers):
    verdicts = {"v": {"ok": ok, "detail": "" if ok else "unsupported"}}
    return {"id": i, "text": i, "ungrounded": [], "unresolved": [], "weak": [], "derived": [],
            "verdicts": verdicts, **tiers}  # fmt: skip


def test_an_unresolved_claim_is_neither_a_false_abstain_nor_an_invention():
    year = [("year", "2024")]
    rows = [
        _row("blocked-cannot-tell", False, unresolved=year),
        _row("blocked-grounded", False),
        _row("blocked-invented", False, ungrounded=[("number", "9")], unresolved=year),
        _row("shipped-cannot-tell", True, unresolved=year),
        _row("shipped-clean", True),
    ]
    s = R.summarize(rows, "v")
    assert (s["blocked"], s["blocked_invented"], s["blocked_unresolved"]) == (3, 1, 1)
    assert s["false_abstains"] == 1  # only the block the auditor grounds completely
    assert (s["shipped"], s["shipped_flagged"], s["shipped_unresolved"]) == (2, 0, 1)
    text = R.render(rows, [], "v", "v", "x.jsonl")
    assert "### blocked-cannot-tell: unresolved" in text
    assert "### blocked-grounded: false abstain" in text
    assert "### blocked-invented: invented" in text
    assert "## Shipped with an unresolved claim: 1" in text and "### shipped-cannot-tell" in text


def test_every_replayed_row_carries_its_unresolved_claims():
    rows, _ = _replayed()
    assert all(r["unresolved"] == [] for r in rows)


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


def test_both_sides_of_a_replay_can_be_pinned_to_a_revision():
    # a replay of two committed verifiers reads the same whatever the working tree holds
    pinned = R.verifiers("3c235d1", "590188e")
    assert list(pinned) == ["verifier at 3c235d1", "verifier at 590188e"]
    assert all(v is not verify.verify for v in pinned.values())
    live = R.verifiers("HEAD", None)
    assert list(live) == ["verifier at HEAD", "verifier now"]
    assert live["verifier now"] is verify.verify


def test_the_report_does_not_say_which_side_produced_the_run():
    # either side may be the one the run was made with: the replay of a later verifier on an
    # earlier run's drafts has the run's own verifier on the left
    rows, not_stored = _replayed()
    text = R.render(rows, not_stored, "old", "new", "x.jsonl")
    assert "produced this run" not in text
    assert "`old` and `new` are two versions of `ledgerql/verify.py`" in text
