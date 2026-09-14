"""Canonical abstain-decision scoring, shared by `run_eval.py` (the
official per-run metrics) and `diagnose_abstains.py` (the post-hoc
diagnostic) -- kept in exactly one place after PHASE_5_5_AMENDMENT_1.md
found the two had already drifted apart on the definition of "correct
abstain": `run_eval.py` required an exact `reason_code` match,
`diagnose_abstains.py` (before its own Task 0 fix) checked behaviour
only. This is the project's sixth run-in with the same
two-sources-of-truth bug class -- see DECISIONS.md for the other five.

`evals/README.md` section 5 defines "abstain precision" as a question
about the *decision* (correct abstains / all abstains), but the shipped
`compute_abstain_metrics()` silently required an exact reason_code
match too, folding "reason-code accuracy" (a metric section 5 lists
separately) into the headline number. A run that correctly refused
71.0% of the time looked like a 29.0% system. Amendment 1 requires
reporting both, always, side by side -- see `abstain_precision_decision`
vs `abstain_precision_strict` below.
"""

from __future__ import annotations

import re

ABSTAIN_EXPECTED_BEHAVIORS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}

# Matches a gold case's accept_alternatives entries shaped like
# "ABSTAIN:SCHEMA_MISMATCH" or "ABSTAIN:SCHEMA_MISMATCH -- <explanation>"
# (real gold.jsonl cases carry trailing prose after the code). Entries
# that aren't this shape (e.g. an ANSWER_WITH_ASSUMPTION alternative
# describing a different acceptable answer) name no reason code and are
# ignored here -- they're not this function's concern.
_ALT_ABSTAIN_CODE_RE = re.compile(r"^ABSTAIN:([A-Z_]+)")


def acceptable_reason_codes(gold_case: dict) -> set[str]:
    """Every reason_code that counts as a correct abstain reason for this
    gold case: its own `reason_code` (if any) plus any `ABSTAIN:CODE`
    entries in `accept_alternatives` (PHASE_5_5_AMENDMENT_1.md, part B).
    For an ANSWER_WITH_ASSUMPTION case, `reason_code` is `None` by
    design (see evals/README.md section 2) -- accept_alternatives is
    the field that actually names an acceptable abstain code, if any.
    """
    codes = set()
    if gold_case.get("reason_code"):
        codes.add(gold_case["reason_code"])
    for alt in gold_case.get("accept_alternatives") or []:
        match = _ALT_ABSTAIN_CODE_RE.match(alt)
        if match:
            codes.add(match.group(1))
    return codes


def compute_abstain_metrics(per_case: list[dict], cases_by_id: dict) -> dict:
    """Returns both the decision-level and reason-code-strict metrics,
    named explicitly so neither can be reported as a bare, ambiguous
    "abstain precision" again (PHASE_5_5_AMENDMENT_1.md, part A):

    - `*_decision`: was abstaining the right call at all, regardless of
      which reason code was given.
    - `*_strict`: was abstaining the right call, AND was the stated
      reason code itself correct (or an accepted alternative).
    - `reason_code_accuracy`: of the cases where abstaining was the
      right call, how often was the stated reason also right --
      isolates the reason-code-naming failure from the abstain-or-not
      decision itself.
    """
    all_abstains = [r for r in per_case if r["answer"] is None]
    decision_correct = [
        r for r in all_abstains if cases_by_id[r["id"]]["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
    ]
    strict_correct = [
        r
        for r in decision_correct
        if r.get("reason_code") in acceptable_reason_codes(cases_by_id[r["id"]])
    ]
    expected_abstains = [
        c for c in cases_by_id.values() if c["expected"] in ABSTAIN_EXPECTED_BEHAVIORS
    ]

    n_abstains = len(all_abstains)
    n_expected = len(expected_abstains)
    n_decision = len(decision_correct)
    n_strict = len(strict_correct)

    return {
        "all_abstains": n_abstains,
        "expected_abstains": n_expected,
        "decision_correct_abstains": n_decision,
        "strict_correct_abstains": n_strict,
        "abstain_precision_decision": n_decision / n_abstains if n_abstains else 0.0,
        "abstain_precision_strict": n_strict / n_abstains if n_abstains else 0.0,
        "abstain_recall_decision": n_decision / n_expected if n_expected else 0.0,
        "abstain_recall_strict": n_strict / n_expected if n_expected else 0.0,
        "reason_code_accuracy": n_strict / n_decision if n_decision else 0.0,
    }
