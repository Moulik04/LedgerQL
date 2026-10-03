"""The comparison harness's findings, pinned: where the verifier and the independent audit differ
on planted values and on correct restatements (`evals/audit_vs_verify.py`). If `verify.py` changes,
this fails and the DECISIONS entry that cites these blind spots needs revisiting."""

from evals import audit_vs_verify as A


def test_the_auditor_catches_every_planted_invented_value():
    missed = [p["form"] for p in A.plant_table() if not p["audit_catches"]]
    assert missed == []


def test_the_verifier_misses_these_planted_forms():
    # Within its 1% tolerance, spelled out (it never reads words), and a form-code lookalike.
    missed = {p["form"] for p in A.plant_table() if not p["verifier_catches"]}
    assert missed == {
        "digits",
        "decimal",
        "magnitude word",
        "spelled-out integer",
        "spelled-out scale",
        "spelled-out decimal",
        "form code lookalike",
    }


def test_the_auditor_accepts_every_correct_restatement_but_a_coarse_rounding_is_weak_not_clean():
    refused = [h["form"] for h in A.honest_table() if not h["audit_accepts"]]
    assert refused == []


def test_the_verifier_refuses_these_correct_restatements():
    refused = {h["form"] for h in A.honest_table() if not h["verifier_accepts"]}
    assert refused == {
        "abbreviation B",
        "abbreviation bn",
        "abbreviation T",
        "fiscal year, FY form",
        "ordinal",
    }
