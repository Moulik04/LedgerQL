"""Task 1 signal search: does any signal separate correct answers from wrong
ones, judged by AUROC on every answered case -- not a fitted calibrator.

With 23 (30B) and 18 (32B) confidently-wrong answers, 8 of them in the calib
split, nothing fitted would generalise, so this only measures how well each
candidate signal ranks correct above wrong. The population is the shipped
(exec_error repair off) config's answered cases: exactly the set the
confidently-wrong rate is computed over, so the counts reconcile with it.

The label is the vote winner's correctness, re-executed locally with the same
guard->execute->vote path as the live pipeline (see passn_scoring.py). An
ABSTAIN-expected case that was answered is wrong by definition.

Signals, as specced in PHASE_5_5_MASTER_PROMPT.md Task 1:
- agreement: winning cluster size / N. Recomputed offline; must equal the
  logged `confidence`.
- guardrail_clean: 1 if no guardrail flagged the winner. A winner passed its
  guard, and guardrails.validate() returns no events on a pass and never
  rewrites semantically (guard.sql differs from the raw SQL only by sqlglot's
  re-render), so this is constant over winners by construction.
- verifier_pass: 1 unless the verifier vetoed with UNGROUNDED_ANSWER. An
  answered case is by definition one the verifier passed: constant.
- result_nonempty: 1 if the winning result has rows.
- schema_margin: not computable. There is no retrieval stage;
  schema_index.get_schema_context() injects the whole schema every time.
- guard_reject_frac (extra): negated share of candidates the guard rejected.

Cross-model agreement (`cross_model_pairs`) is a further candidate signal: for
cases two models both answered, does one model's winner match the other's?
"""

from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

import duckdb

from evals.passn_scoring import GOLD_PATH, _run_candidate, load_jsonl
from evals.replay_repair_off import revert_exec_error_repairs
from evals.replay_year_rule import apply_year_rule
from evals.run_eval import results_match

SIGNALS = [
    "agreement",
    "guardrail_clean",
    "result_nonempty",
    "verifier_pass",
    "guard_reject_frac",
]
_SCORED = ("ANSWER", "ANSWER_WITH_ASSUMPTION")
_BUCKETS = ("agree", "differ", "other_abstained")


def auroc(pos: list[float], neg: list[float]) -> float | None:
    """P(score_pos > score_neg), ties counted half. Positive class is
    "winner correct". None when either class is empty."""
    if not pos or not neg:
        return None
    total = 0.0
    for p in pos:
        for n in neg:
            total += 1.0 if p > n else 0.5 if p == n else 0.0
    return total / (len(pos) * len(neg))


def bootstrap_auroc_ci(
    pos: list[float], neg: list[float], n_boot: int = 2000, seed: int = 0
) -> tuple[float, float]:
    """95% percentile bootstrap CI, resampling each class independently."""
    rng = random.Random(seed)
    stats = sorted(
        auroc(rng.choices(pos, k=len(pos)), rng.choices(neg, k=len(neg))) for _ in range(n_boot)
    )
    return stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]


def _key(row: tuple) -> tuple:
    return tuple(f"{v:.6g}" if isinstance(v, float) else str(v) for v in row)


def rows_equivalent(a: list[tuple], b: list[tuple], rel_tol: float = 1e-6) -> bool:
    """Same result set: order-insensitive, floats equal within `rel_tol`."""
    if len(a) != len(b):
        return False
    for ra, rb in zip(sorted(a, key=_key), sorted(b, key=_key), strict=True):
        if len(ra) != len(rb):
            return False
        for x, y in zip(ra, rb, strict=True):
            if isinstance(x, float) or isinstance(y, float):
                try:
                    if abs(x - y) > rel_tol * max(abs(x), abs(y), 1.0):
                        return False
                except TypeError:
                    return False
            elif x != y:
                return False
    return True


def build_rows(
    per_case: list[dict], cases_by_id: dict, db_path: str, year_rule: bool = False
) -> list[dict]:
    """One row per case for the shipped (repair-off) config, carrying every
    signal plus the winner's correctness and result rows. With `year_rule`, the
    year-grounding verifier is applied first, so an answer it rejects is an
    abstain, not an answer, exactly as the pipeline now produces."""
    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    rows = []
    try:
        shipped = revert_exec_error_repairs(per_case)
        for rec in apply_year_rule(shipped) if year_rule else shipped:
            case = cases_by_id[rec["id"]]
            cands = rec.get("candidates") or []
            n = len(cands)
            executed = [_run_candidate(c["sql"], db_path) for c in cands]

            # consensus.vote(): biggest cluster of identical result sets, ties
            # to the earliest candidate.
            clusters: dict[tuple, list[int]] = {}
            for i, (_, result) in enumerate(executed):
                if result is not None:
                    clusters.setdefault(tuple(sorted(map(_key, result))), []).append(i)
            if clusters:
                winning = max(clusters.values(), key=len)
                winner = winning[0]
                winner_rows = executed[winner][1]
                agreement = len(winning) / n
                winner_events = cands[winner]["events"]
            else:
                winner_rows, agreement, winner_events = None, 0.0, None

            winner_correct = False
            if case["expected"] in _SCORED and case.get("gold_sql") and winner_rows is not None:
                gold_rows = con.execute(case["gold_sql"]).fetchall()
                winner_correct = results_match(
                    gold_rows, winner_rows, case["compare"], case.get("tolerance", 1e-6)
                )
            answered = rec["answer"] is not None
            rows.append(
                {
                    "id": rec["id"],
                    "tier": case["tier"],
                    "expected": case["expected"],
                    "answered": answered,
                    "reason_code": rec.get("reason_code"),
                    "logged_confidence": rec.get("confidence"),
                    "agreement": agreement,
                    "guardrail_clean": None if winner_events is None else int(not winner_events),
                    "result_nonempty": int(bool(winner_rows)),
                    "verifier_pass": (
                        0
                        if rec.get("reason_code") == "UNGROUNDED_ANSWER"
                        else (1 if answered else None)
                    ),
                    "guard_reject_frac": -sum(not c["guard_ok"] for c in cands) / n if n else None,
                    "winner_correct": winner_correct,
                    "winner_rows": winner_rows,
                }
            )
    finally:
        con.close()
    return rows


def signal_report(rows: list[dict], signals: list[str] = SIGNALS) -> dict:
    """Per signal, over answered rows: AUROC for ranking correct above wrong,
    its bootstrap CI, both class distributions, and whether the signal is
    constant (AUROC 0.5 by construction, not by measurement)."""
    answered = [r for r in rows if r["answered"]]
    pos_rows = [r for r in answered if r["winner_correct"]]
    neg_rows = [r for r in answered if not r["winner_correct"]]
    out = {}
    for name in signals:
        pos = [r[name] for r in pos_rows if r.get(name) is not None]
        neg = [r[name] for r in neg_rows if r.get(name) is not None]
        a = auroc(pos, neg)
        out[name] = {
            "auroc": a,
            "ci": bootstrap_auroc_ci(pos, neg) if pos and neg else None,
            "n_correct": len(pos),
            "n_wrong": len(neg),
            "correct_dist": dict(sorted(Counter(pos).items())),
            "wrong_dist": dict(sorted(Counter(neg).items())),
            "constant": len(set(pos) | set(neg)) <= 1,
        }
    return out


def cross_model_pairs(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    """For every case both models answered, whether their winners agree."""
    by_id_b = {r["id"]: r for r in rows_b}
    pairs = []
    for a in rows_a:
        b = by_id_b.get(a["id"])
        if b is None or not (a["answered"] and b["answered"]):
            continue
        pairs.append(
            {
                "id": a["id"],
                "xmodel_match": int(
                    rows_equivalent(a["winner_rows"] or [], b["winner_rows"] or [])
                ),
                "correct_a": a["winner_correct"],
                "correct_b": b["winner_correct"],
            }
        )
    return pairs


def policy_breakdown(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """Model A's answers, bucketed by what model B did on the same case:
    `agree` (B answered with the same result), `differ` (B answered
    differently), `other_abstained` (B did not answer). The buckets partition
    A's answers. `policy` is the rule "answer only where both answered and
    agree", i.e. the `agree` bucket. An abstention by the other model is
    reported apart from a disagreement, because it is a separate signal."""
    by_id_b = {r["id"]: r for r in rows_b}
    buckets = {name: {"n": 0, "correct": 0, "wrong": 0} for name in _BUCKETS}
    for a in rows_a:
        if not a["answered"]:
            continue
        b = by_id_b.get(a["id"])
        if b is None or not b["answered"]:
            name = "other_abstained"
        elif rows_equivalent(a["winner_rows"] or [], b["winner_rows"] or []):
            name = "agree"
        else:
            name = "differ"
        buckets[name]["n"] += 1
        buckets[name]["correct" if a["winner_correct"] else "wrong"] += 1
    return {
        "buckets": buckets,
        "answered": sum(v["n"] for v in buckets.values()),
        "correct": sum(v["correct"] for v in buckets.values()),
        "wrong": sum(v["wrong"] for v in buckets.values()),
        "policy": {"answered": buckets["agree"]["n"], "correct": buckets["agree"]["correct"],
                   "wrong": buckets["agree"]["wrong"]},
    }  # fmt: skip


def _fmt_ci(a: float | None, ci: tuple[float, float] | None) -> str:
    return "n/a" if a is None else f"{a:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--models", nargs=2, default=["qwen3_30b", "qwen25_32b"])
    ap.add_argument(
        "--year-rule",
        action="store_true",
        help="apply the year-grounding verifier first (replay_year_rule)",
    )
    args = ap.parse_args(argv)

    gold = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    rows = {
        m: build_rows(
            load_jsonl(args.reports_dir / f"eval_bridges2_{m}_measured.jsonl"),
            gold,
            args.db,
            year_rule=args.year_rule,
        )
        for m in args.models
    }

    for m, rs in rows.items():
        answered = [r for r in rs if r["answered"]]
        wrong = [r for r in answered if not r["winner_correct"]]
        rate = len(wrong) / len(answered)
        print(f"\n== {m}: answered {len(answered)}, wrong {len(wrong)} ({rate:.1%})")
        print(f"  {'signal':<18} {'AUROC [95% CI]':<24} note")
        for name, s in signal_report(rs).items():
            note = "constant among answered: chance by construction" if s["constant"] else ""
            print(f"  {name:<18} {_fmt_ci(s['auroc'], s['ci']):<24} {note}")
        print("  schema_margin      n/a                      no retrieval stage exists")
        ag = signal_report(rs, ["agreement"])["agreement"]
        print(f"  agreement: correct {ag['correct_dist']}  wrong {ag['wrong_dist']}")

    a, b = args.models
    pairs = cross_model_pairs(rows[a], rows[b])
    print(f"\n== cross-model agreement: {len(pairs)} cases both {a} and {b} answered")
    for own, key in ((a, "correct_a"), (b, "correct_b")):
        pos = [p["xmodel_match"] for p in pairs if p[key]]
        neg = [p["xmodel_match"] for p in pairs if not p[key]]
        area = auroc(pos, neg)
        ci = bootstrap_auroc_ci(pos, neg) if pos and neg else None
        print(f"  {own}: AUROC {_fmt_ci(area, ci)}  (correct n={len(pos)}, wrong n={len(neg)})")
        agree = [p for p in pairs if p["xmodel_match"]]
        differ = [p for p in pairs if not p["xmodel_match"]]
        for name, group in (("models agree", agree), ("models differ", differ)):
            wrong_n = sum(not p[key] for p in group)
            share = f"{wrong_n / len(group):.0%}" if group else "n/a"
            print(f"    {name:<14} n={len(group):>2}  wrong={wrong_n:>2}  ({share} wrong)")
    for own, other in ((a, b), (b, a)):
        out = policy_breakdown(rows[own], rows[other])
        base_rate = out["wrong"] / out["answered"]
        pol = out["policy"]
        print(f"\n== {own}: its {out['answered']} answers by what {other} did")
        for name, v in out["buckets"].items():
            print(f"  {name:<16} n={v['n']:>2}  right={v['correct']:>2}  wrong={v['wrong']:>2}")
        print(
            f"  policy 'answer only where both answered and agree': "
            f"confidently-wrong {base_rate:.1%} -> {pol['wrong'] / pol['answered']:.1%}; "
            f"answers {out['answered']} -> {pol['answered']} "
            f"({pol['answered'] - out['answered']:+d}, "
            f"{(pol['answered'] - out['answered']) / out['answered']:+.0%}); "
            f"correct answers {out['correct']} -> {pol['correct']} "
            f"({pol['correct'] - out['correct']:+d})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
