# ruff: noqa: E501  (markdown table rows are single lines)
"""Phase 6 question, answered offline: at a FIXED budget of 5 candidates, does a pool
drawn across models and prompts beat 5 samples from one model?

Every case has 45 candidates from the bake-off (3 models x 3 prompts x 5 samples).
The fair comparison holds the budget at 5 and varies only where they come from:

- `single run`: a run's own 5 samples, exact (9 of them: 3 models x 3 prompts).
- `models, one prompt`: 5 drawn at random from the 15 that three models wrote for one prompt.
- `prompts, one model`: 5 drawn at random from the 15 that one model wrote for three prompts.
- `all 45`: 5 drawn at random from all 45.
- `5 distinct runs`: one candidate from each of 5 different runs of the 9.

Each drawn pool is scored on **pass@N** (does any of the 5 match gold) and on
**agreement-selected pass@1** (the pipeline's own vote among the 5: biggest cluster of
identical results, ties to the earliest drawn). Random configurations are expectations
over `n_draws` draws per case; differences against the single-run baseline carry a
95% bootstrap CI that resamples *cases*. Comparing against the mean single run is the
fair baseline; comparing against the best single run is conservative, because that run
was picked in hindsight from nine.

    python -m evals.pool_experiment --write reports/pool_experiment.md
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from pathlib import Path

from evals.rescore_v2 import (
    DEFAULT_DB,
    LABELS,
    VERSIONS,
    Cand,
    Gold,
    Pool,
    load_evidence,
    score_bakeoff,
    vote_winner,
)

K = 5
Tagged = tuple[str, Cand]  # (run key, candidate)


def score_draw(draw: list[Cand], version: str) -> tuple[bool, bool]:
    """(pass@N, agreement-selected pass@1) for one pool of candidates, in draw order."""
    pass_n = any(c.verdict[version] for c in draw)
    winner = vote_winner([c.key for c in draw])
    return pass_n, winner is not None and draw[winner].verdict[version]


def expected_over_draws(
    pool: list[Tagged], k: int, n_draws: int, rng: random.Random, versions=VERSIONS
) -> dict[str, tuple[float, float]]:
    """Expected (pass@N, pass@1) for k candidates drawn without replacement from `pool`."""
    totals = {v: [0, 0] for v in versions}
    for _ in range(n_draws):
        draw = [c for _, c in rng.sample(pool, k)]
        for v in versions:
            pn, p1 = score_draw(draw, v)
            totals[v][0] += pn
            totals[v][1] += p1
    return {v: (t[0] / n_draws, t[1] / n_draws) for v, t in totals.items()}


def stratified_draw(pool: list[Tagged], k: int, rng: random.Random) -> list[Tagged]:
    """One candidate from each of k distinct runs."""
    by_run: dict[str, list[Tagged]] = defaultdict(list)
    for item in pool:
        by_run[item[0]].append(item)
    runs = rng.sample(sorted(by_run), k)
    return [rng.choice(by_run[r]) for r in runs]


def expected_stratified(
    pool: list[Tagged], k: int, n_draws: int, rng: random.Random, versions=VERSIONS
) -> dict[str, tuple[float, float]]:
    totals = {v: [0, 0] for v in versions}
    for _ in range(n_draws):
        draw = [c for _, c in stratified_draw(pool, k, rng)]
        for v in versions:
            pn, p1 = score_draw(draw, v)
            totals[v][0] += pn
            totals[v][1] += p1
    return {v: (t[0] / n_draws, t[1] / n_draws) for v, t in totals.items()}


def bootstrap_mean_ci(values: list[float], n_boot: int = 2000, seed: int = 0):
    """95% percentile bootstrap CI of the mean, resampling the values (cases)."""
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def _run_key(p: Pool) -> str:
    return f"{p.model}/{p.profile}"


def per_case_expectations(
    pools: list[Pool], k: int = K, n_draws: int = 2000, seed: int = 0
) -> dict[str, dict[str, dict[str, tuple[float, float]]]]:
    """{config: {case id: {version: (E pass@N, E pass@1)}}} for every configuration.
    A config with sub-configurations (three prompts, three models) is keyed
    `name|sub`; the caller averages them."""
    rng = random.Random(seed)
    by_case: dict[str, list[Pool]] = defaultdict(list)
    for p in pools:
        by_case[p.id].append(p)
    out: dict[str, dict] = defaultdict(dict)
    for cid, case_pools in sorted(by_case.items()):
        tagged = [(_run_key(p), c) for p in case_pools for c in p.cands]
        for p in case_pools:  # a run's own 5, in candidate order: exact, no randomness
            out[f"single run|{_run_key(p)}"][cid] = {
                v: tuple(map(float, score_draw(p.cands, v))) for v in VERSIONS
            }
        for prompt in sorted({p.profile for p in case_pools}):
            sub = [t for t in tagged if t[0].endswith("/" + prompt)]
            out[f"models, one prompt|{prompt}"][cid] = expected_over_draws(sub, k, n_draws, rng)
        for model in sorted({p.model for p in case_pools}):
            sub = [t for t in tagged if t[0].startswith(model + "/")]
            out[f"prompts, one model|{model}"][cid] = expected_over_draws(sub, k, n_draws, rng)
        out["all 45|all"][cid] = expected_over_draws(tagged, k, n_draws, rng)
        out["5 distinct runs|all"][cid] = expected_stratified(tagged, k, n_draws, rng)
    return dict(out)


def _config_mean(per_case: dict, names: list[str], version: str, which: int) -> list[float]:
    """Per-case expectation averaged over the sub-configurations in `names`, case order fixed."""
    cids = sorted(per_case[names[0]])
    return [sum(per_case[n][c][version][which] for n in names) / len(names) for c in cids]


def summarize(per_case: dict) -> dict:
    groups: dict[str, list[str]] = defaultdict(list)
    for name in per_case:
        groups[name.split("|")[0]].append(name)
    baseline_names = groups["single run"]
    out: dict = {"groups": {}, "n_cases": len(per_case[baseline_names[0]])}
    for version in VERSIONS:
        best_run = max(
            baseline_names,
            key=lambda n: sum(per_case[n][c][version][0] for c in per_case[n]),
        )
        baseline = {w: _config_mean(per_case, baseline_names, version, w) for w in (0, 1)}
        best = {w: _config_mean(per_case, [best_run], version, w) for w in (0, 1)}
        for g, names in groups.items():
            row = {}
            for w, label in ((0, "pass_n"), (1, "pass_1")):
                vals = _config_mean(per_case, names, version, w)
                diff = [a - b for a, b in zip(vals, baseline[w], strict=True)]
                diff_best = [a - b for a, b in zip(vals, best[w], strict=True)]
                each = [
                    sum(_config_mean(per_case, [n], version, w)) for n in names
                ]  # totals of each sub-configuration
                row[label] = {
                    "mean": sum(vals),
                    "min": min(each),
                    "max": max(each),
                    "vs_mean_single": (
                        sum(diff),
                        *[x * len(diff) for x in bootstrap_mean_ci(diff)],
                    ),
                    "vs_best_single": (
                        sum(diff_best),
                        *[x * len(diff_best) for x in bootstrap_mean_ci(diff_best)],
                    ),
                }
            out["groups"].setdefault(g, {})[version] = row
        out.setdefault("best_run", {})[version] = best_run
    return out


def render(summary: dict, k: int = K) -> str:
    n = summary["n_cases"]
    lines = [
        "# Fixed-budget pool experiment",
        "",
        f"Budget: {k} candidates per case, {n} ANSWER cases. Expected cases solved (of {n}). "
        "`vs mean single run` is the pooled figure minus the mean of the nine single runs, "
        "with a 95% bootstrap CI over cases; `vs best` uses the single run that scored best "
        "on pass@N in hindsight, so it is a conservative comparison. Method: "
        "`evals/pool_experiment.py`.",
        "",
    ]
    names = {
        "single run": "single run (5 samples, one model, one prompt)",
        "models, one prompt": "5 of the 15 from three models, one prompt",
        "prompts, one model": "5 of the 15 from three prompts, one model",
        "all 45": "5 of all 45 (three models, three prompts)",
        "5 distinct runs": "one from each of 5 distinct runs",
    }
    for version in VERSIONS:
        lines += [
            f"## {LABELS[version]}",
            "",
            f"Best single run on pass@N (hindsight): {summary['best_run'][version]}.",
            "",
            "| pool | pass@N | vs mean single [95% CI] | vs best single [95% CI] "
            "| pass@1 (vote) | vs mean single [95% CI] | vs best single [95% CI] |",
            "|---|---|---|---|---|---|---|",
        ]
        for g, label in names.items():
            r = summary["groups"][g][version]
            span = (
                f" ({r['pass_n']['min']:.1f}-{r['pass_n']['max']:.1f})"
                if r["pass_n"]["min"] != r["pass_n"]["max"]
                else ""
            )

            def cell(x):
                return f"{x[0]:+.1f} [{x[1]:+.1f}, {x[2]:+.1f}]"

            lines.append(
                f"| {label} | {r['pass_n']['mean']:.1f}{span} | {cell(r['pass_n']['vs_mean_single'])} "
                f"| {cell(r['pass_n']['vs_best_single'])} | {r['pass_1']['mean']:.1f} "
                f"| {cell(r['pass_1']['vs_mean_single'])} | {cell(r['pass_1']['vs_best_single'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    pools = score_bakeoff(load_evidence(), Gold(args.db))
    text = render(summarize(per_case_expectations(pools, args.k, args.draws, args.seed)), args.k)
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
