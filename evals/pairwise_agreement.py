"""Cross-model agreement AUROC for every pair of models in the bake-off.

For an ordered pair (A -> B): over the cases both models produced a winner,
does B's winning result match A's, and does that match/no-match rank A's correct
answers above its wrong ones? Cross-model agreement between the Qwen3-30B and
Qwen2.5-32B pipeline runs separated correct from wrong far better than either
model's own five-sample agreement (DECISIONS.md 2026-09-29); models that differ
more may disagree more usefully, and once the generation-only runs exist this
costs nothing.

Inputs are `gen_only_<profile>.jsonl` files from `evals/gen_only_eval.py`, one
per model, given as `label=path`. A gen-only case has no abstention, so "answered"
means the vote produced a winner (not every candidate failed). Nothing is fitted:
the rule is match/no-match, so this reports AUROC with a bootstrap CI and the
policy "answer only where both agree" in full, like `evals/signal_precheck.py`.

    python -m evals.pairwise_agreement 30b=runs/1/gen_only_current.jsonl \
        xiyan=runs/2/gen_only_xiyan.jsonl omnisql=runs/3/gen_only_omnisql.jsonl
"""

from __future__ import annotations

import argparse
from itertools import permutations
from pathlib import Path

from evals.passn_scoring import load_jsonl
from evals.signal_precheck import (
    auroc,
    bootstrap_auroc_ci,
    cross_model_pairs,
    policy_breakdown,
)


def load_model(path: Path) -> list[dict]:
    return [
        {
            "id": r["id"],
            "answered": r["reason_code"] is None,
            "winner_correct": r["execution_correct"] is True,
            "winner_rows": r["rows"],
        }
        for r in load_jsonl(Path(path))
    ]


def pair_stats(rows_a: list[dict], rows_b: list[dict]) -> dict:
    pairs = cross_model_pairs(rows_a, rows_b)
    pos = [p["xmodel_match"] for p in pairs if p["correct_a"]]
    neg = [p["xmodel_match"] for p in pairs if not p["correct_a"]]
    breakdown = policy_breakdown(rows_a, rows_b)
    return {
        "n_both_answered": len(pairs),
        "auroc": auroc(pos, neg),
        "ci": bootstrap_auroc_ci(pos, neg) if pos and neg else None,
        "n_correct": len(pos),
        "n_wrong": len(neg),
        "buckets": breakdown["buckets"],
        "policy": breakdown["policy"],
        "answered": breakdown["answered"],
        "correct": breakdown["correct"],
        "wrong": breakdown["wrong"],
    }


def _fmt(s: dict) -> str:
    area = "n/a" if s["auroc"] is None else f"{s['auroc']:.3f} [{s['ci'][0]:.3f}, {s['ci'][1]:.3f}]"
    pol = s["policy"]
    before = f"{s['wrong']}/{s['answered']}" if s["answered"] else "0/0"
    after = f"{pol['wrong']}/{pol['answered']}"
    return (
        f"AUROC {area} over {s['n_both_answered']} shared cases "
        f"(A right {s['n_correct']}, wrong {s['n_wrong']}); policy 'answer only where both "
        f"agree': wrong {before} -> {after}, answers {s['answered']} -> {pol['answered']}, "
        f"correct {s['correct']} -> {pol['correct']}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("models", nargs="+", metavar="label=path")
    args = ap.parse_args(argv)
    models = {}
    for spec in args.models:
        label, _, path = spec.partition("=")
        if not path:
            ap.error(f"expected label=path, got {spec!r}")
        models[label] = load_model(Path(path))
    for a, b in permutations(models, 2):
        print(f"{a} -> {b}: {_fmt(pair_stats(models[a], models[b]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
