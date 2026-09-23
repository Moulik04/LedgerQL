"""Confidently-wrong rate: among answered cases (the system did not
abstain), the fraction whose result doesn't match gold.

`ledgerql/verify.py` checks every number a generated answer states against
that SAME query's own executed result -- never against gold. A wrong SQL
query that returns wrong rows, whose answer restates those rows, passes
verify.py: every number it states really is in its own result, that result
is just an answer to the wrong question. DECISIONS.md's 2026-09-21
"exec_error repair cut" entry found exactly this on real runs (T06, O04, H08
on the 30B; M03, H02 on the 32B all carry `hallucinated_numbers: []` while
being wrong). So "0.0% hallucinated numbers" means zero UNGROUNDED numbers,
not zero WRONG ones -- this metric names the wrong ones directly, and is
reported beside hallucinated_number_rate everywhere that number appears
(evals/run_eval.py, evals/replay_repair_off.py) so neither can be read alone
as "0% wrong".
"""

from __future__ import annotations

from collections import defaultdict

_ANSWER_EXPECTED = {"ANSWER", "ANSWER_WITH_ASSUMPTION"}


def is_confidently_wrong(record: dict, expected: str) -> bool:
    """True if the system answered (did not abstain) and that answer is
    wrong. For an ANSWER/ANSWER_WITH_ASSUMPTION case, "wrong" is
    `execution_correct is not True` (covers False and a missing key alike --
    a record with no `execution_correct` field, e.g. a pipeline-crash
    record that still carries an answer, must count as wrong, not be
    silently skipped). For an ABSTAIN case that was answered anyway, there
    is no gold result to compare against: any answer is wrong by
    definition, since refusing was the required behaviour.
    """
    if record["answer"] is None:
        return False
    if expected in _ANSWER_EXPECTED:
        return record.get("execution_correct") is not True
    return True


def compute_confidently_wrong_rate(per_case: list[dict], cases_by_id: dict) -> dict:
    answered = [r for r in per_case if r["answer"] is not None]

    tier_answered: dict[str, int] = defaultdict(int)
    tier_wrong: dict[str, int] = defaultdict(int)
    wrong_count = 0
    for record in answered:
        case = cases_by_id[record["id"]]
        tier_answered[case["tier"]] += 1
        if is_confidently_wrong(record, case["expected"]):
            wrong_count += 1
            tier_wrong[case["tier"]] += 1

    return {
        "confidently_wrong_count": wrong_count,
        "confidently_wrong_rate": wrong_count / len(answered) if answered else 0.0,
        "confidently_wrong_by_tier": {
            tier: tier_wrong[tier] / n for tier, n in tier_answered.items()
        },
    }
