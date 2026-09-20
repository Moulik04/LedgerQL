"""Repair-pass scoring, split by trigger.

The triggers (ledgerql/repair.py) are different bets, so their value has to be
separable: reported together, a strong trigger would hide a weak or harmful
one. ``empty_entity_bound`` was a third trigger until 2026-09-20 (cut: an empty
result carries no error to feed back); old reports that carry it still tally.

"Rescued" means the repair turned an abstain into an answer. It is not the
same as "helped": ``rescued_correct`` counts rescues that match gold on cases
where answering is right, and ``rescued_should_have_abstained`` counts rescues
on cases where refusing was required -- a correct refusal converted into an
answer, which is the failure mode a repair pass risks and the one that must
never be netted against the wins.
"""

from __future__ import annotations

from ledgerql.repair import TRIGGERS

_ANSWER_EXPECTED = {"ANSWER", "ANSWER_WITH_ASSUMPTION"}


def _empty() -> dict:
    return {
        "attempted": 0,
        "rescued": 0,
        "rescued_correct": 0,
        "rescued_should_have_abstained": 0,
        "rescue_rate": 0.0,
    }


def compute_repair_stats(per_case: list[dict], cases_by_id: dict) -> dict:
    by_trigger = {trigger: _empty() for trigger in TRIGGERS}
    for record in per_case:
        repair = record.get("repair")
        if not repair:
            continue
        # A trigger retired after a report was written (empty_entity_bound, cut
        # 2026-09-20) still gets its own bucket: nothing is silently dropped.
        stats = by_trigger.setdefault(repair["trigger"], _empty())
        stats["attempted"] += 1
        if record["answer"] is None:
            continue
        stats["rescued"] += 1
        expected = cases_by_id[record["id"]]["expected"]
        if expected in _ANSWER_EXPECTED and record.get("execution_correct") is True:
            stats["rescued_correct"] += 1
        if expected == "ABSTAIN":
            stats["rescued_should_have_abstained"] += 1

    total = _empty()
    for stats in by_trigger.values():
        for key in ("attempted", "rescued", "rescued_correct", "rescued_should_have_abstained"):
            total[key] += stats[key]
    for stats in (*by_trigger.values(), total):
        stats["rescue_rate"] = stats["rescued"] / stats["attempted"] if stats["attempted"] else 0.0
    return {"by_trigger": by_trigger, "total": total}
