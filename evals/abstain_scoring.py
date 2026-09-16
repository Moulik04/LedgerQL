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

# Both populations where refusing is an acceptable outcome -- the
# population abstain *precision* is asked of.
ABSTAIN_EXPECTED_BEHAVIORS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}

# The population abstain *recall* is asked of: the cases where refusing is
# REQUIRED, not merely acceptable. Recall used to divide by the 53-case
# ABSTAIN_EXPECTED_BEHAVIORS union, which scored the ideal outcome on an
# ANSWER_WITH_ASSUMPTION case -- answering it correctly with the assumption
# stated -- as a missed abstain, and so rewarded over-abstention. The 19
# assumption cases are reported separately as `assumption_case_handling`.
REQUIRED_ABSTAIN_BEHAVIOR = "ABSTAIN"
ASSUMPTION_BEHAVIOR = "ANSWER_WITH_ASSUMPTION"

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


def assumption_case_handled(record: dict) -> bool:
    """Did the system do one of the two acceptable things on an
    `ANSWER_WITH_ASSUMPTION` case: abstain (acceptable), or answer with a
    result matching gold (the ideal outcome)?

    `execution_correct` is the answer-side signal `run_eval.py` records;
    it is absent from reports written before assumption cases were
    execution-scored, so on those this degrades to counting abstains only
    and the resulting rate is a lower bound. The stronger check -- that
    the assumption was also *stated* -- is `answer_must_state` rubric
    grading, which nothing implements yet (evals/README.md section 3).
    """
    if record["answer"] is None:
        return True
    return record.get("execution_correct") is True


def compute_abstain_metrics(per_case: list[dict], cases_by_id: dict) -> dict:
    """Returns the decision-level and reason-code-strict metrics, named
    explicitly so neither can be reported as a bare, ambiguous "abstain
    precision" again (PHASE_5_5_AMENDMENT_1.md, part A):

    - `*_decision`: was abstaining the right call at all, regardless of
      which reason code was given.
    - `*_strict`: was abstaining the right call, AND was the stated
      reason code itself correct (or an accepted alternative).
    - `reason_code_accuracy`: of the cases where abstaining was the
      right call, how often was the stated reason also right --
      isolates the reason-code-naming failure from the abstain-or-not
      decision itself.

    Precision and recall deliberately ask about different populations:

    - **Precision** is asked of every abstain, and an abstain is a correct
      decision on either population -- required on the 34 `ABSTAIN` cases,
      an accepted alternative on the 19 `ANSWER_WITH_ASSUMPTION` ones.
    - **Recall** is asked only of the 34, where abstaining is *required*.
      Its numerator is drawn from that same population: crediting an
      assumption-case abstain toward it would conflate "took an accepted
      alternative" with "caught a case it had to catch", and could push
      recall above 100%.
    - The 19 get their own `assumption_case_handling`, which counts either
      acceptable outcome, so that answering one correctly stops being
      scored as a recall miss.
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

    required_caught = [
        r for r in decision_correct if cases_by_id[r["id"]]["expected"] == REQUIRED_ABSTAIN_BEHAVIOR
    ]
    required_caught_strict = [
        r for r in strict_correct if cases_by_id[r["id"]]["expected"] == REQUIRED_ABSTAIN_BEHAVIOR
    ]
    required_cases = [c for c in cases_by_id.values() if c["expected"] == REQUIRED_ABSTAIN_BEHAVIOR]

    assumption_ids = {c["id"] for c in cases_by_id.values() if c["expected"] == ASSUMPTION_BEHAVIOR}
    assumption_records = [r for r in per_case if r["id"] in assumption_ids]
    assumption_handled = [r for r in assumption_records if assumption_case_handled(r)]

    n_abstains = len(all_abstains)
    n_decision = len(decision_correct)
    n_strict = len(strict_correct)
    n_required = len(required_cases)
    n_required_caught = len(required_caught)
    n_required_caught_strict = len(required_caught_strict)
    n_assumption = len(assumption_ids)
    n_assumption_handled = len(assumption_handled)

    return {
        "all_abstains": n_abstains,
        "required_abstain_cases": n_required,
        "assumption_cases": n_assumption,
        "decision_correct_abstains": n_decision,
        "strict_correct_abstains": n_strict,
        "required_abstains_caught": n_required_caught,
        "required_abstains_caught_strict": n_required_caught_strict,
        "assumption_cases_handled": n_assumption_handled,
        "abstain_precision_decision": n_decision / n_abstains if n_abstains else 0.0,
        "abstain_precision_strict": n_strict / n_abstains if n_abstains else 0.0,
        "abstain_recall_decision": n_required_caught / n_required if n_required else 0.0,
        "abstain_recall_strict": n_required_caught_strict / n_required if n_required else 0.0,
        "reason_code_accuracy": n_strict / n_decision if n_decision else 0.0,
        "assumption_case_handling": (n_assumption_handled / n_assumption if n_assumption else 0.0),
    }
