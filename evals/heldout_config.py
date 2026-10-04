"""The pinned held-out headline configuration (evals/HELDOUT_PROTOCOL.md 6a).

`heldout_config.json` is an append-only list of declarations. The active one names the code
(`code_commit`, and `ledgerql_tree`: the git tree hash of `ledgerql/`, which changes if and only
if the pipeline code changes), the models, the job scripts, the settings, and how the
entity-linking setting is decided. **Any later change under `ledgerql/` is a new configuration**
that needs its own declaration. A held-out run (`run_eval` or `gen_only_eval` on a
`heldout*.jsonl` file) is refused unless the code tree and the linker environment match the
active declaration and the linker decision has been recorded. That decision is made from the dev
A/B and recorded before any held-out run; it is never chosen from held-out results.

A declaration marked `final` freezes `ledgerql/`: until its `frozen.lifted` is set (after the
held-out runs), no declaration may follow it. A verifier or pipeline issue found meanwhile is
listed in `evals/KNOWN_PIPELINE_ISSUES.md` and not fixed, like a gold issue after the gold freeze.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from pathlib import Path

from evals.rescore_v2 import Pool
from evals.scoring import FrozenGoldError

CONFIG_PATH = Path(__file__).resolve().parent / "heldout_config.json"
REPO = Path(__file__).resolve().parent.parent


def load(path: Path = CONFIG_PATH) -> list[dict]:
    return json.loads(Path(path).read_text())


def active(decls: list[dict] | None = None) -> dict:
    decls = decls if decls is not None else load()
    for i, d in enumerate(decls):
        if d.get("final") and d["frozen"]["lifted"] is None and i != len(decls) - 1:
            raise ValueError(
                f"configuration {d['id']} is final and ledgerql/ is frozen until the held-out runs "
                f"are done: {decls[-1]['id']} cannot be declared. List the issue in "
                f"{d['frozen']['issues_go_to']} instead"
            )
    live = [d for d in decls if d["status"] == "active"]
    if len(live) != 1:
        raise ValueError(f"exactly one declaration must be active, found {len(live)}")
    return live[0]


def current_tree() -> str:
    """The git tree hash of `ledgerql/` at HEAD."""
    out = subprocess.run(
        ["git", "rev-parse", "HEAD:ledgerql"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def require_declared(path, decls: list[dict] | None = None) -> None:
    """Refuse a held-out run whose code or linker setting is not the declared configuration.
    Any other gold file is not checked."""
    if not Path(path).name.startswith("heldout"):
        return
    h = active(decls)
    decision = h["entity_link"]["decision"]
    if decision is None:
        raise FrozenGoldError(
            "the entity linking decision for the held-out configuration is not recorded: decide it "
            "from the dev A/B and record it in evals/heldout_config.json before any held-out run"
        )
    tree = current_tree()
    if tree != h["ledgerql_tree"]:
        raise FrozenGoldError(
            f"ledgerql/ is tree {tree[:10]} but the declared configuration {h['id']} is "
            f"{h['ledgerql_tree'][:10]}: a code change is a new configuration; declare it first"
        )
    enabled = os.environ.get("LEDGERQL_ENTITY_LINK") == "1"
    if enabled != (decision == "on"):
        raise FrozenGoldError(
            f"LEDGERQL_ENTITY_LINK is {'1' if enabled else 'unset'} but the declared decision is "
            f"{decision!r}"
        )


BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261002
EXPECTED_CASES = 50


def case_share_diffs(base: list[Pool], linked: list[Pool], version: str = "v3") -> dict[str, float]:
    """Per case, the share of the N candidates that are correct (strict v3 by default), linked
    minus unlinked. The two conditions must cover the same cases."""
    b = {p.id: p for p in base}
    k = {p.id: p for p in linked}
    if set(b) != set(k):
        raise ValueError(f"the two conditions cover different cases: {sorted(set(b) ^ set(k))}")

    def share(p: Pool) -> float:
        return sum(bool(c.verdict[version]) for c in p.cands) / len(p.cands)

    return {i: share(k[i]) - share(b[i]) for i in sorted(b)}


def bootstrap_ci(
    diffs: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    level: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean over cases (paired: `diffs` are per-case differences).
    Seeded, and pure Python, so the same inputs give the same interval on any machine."""
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(resamples))
    tail = (1 - level) / 2
    return means[int(resamples * tail)], means[int(resamples * (1 - tail)) - 1]


def apply_rule(
    ci_30b: tuple[float, float], ci_xiyan: tuple[float, float], mean_30b: float, mean_xiyan: float
) -> tuple[str, str]:
    """The entity-linking decision rule (protocol 6a, amended 2026-10-02 before either result was
    read): linking is on unless either model's 95% CI for the mean per-case change in the correct
    candidate share (linked minus unlinked) lies entirely below zero."""
    harmed = [name for name, ci in (("Qwen3-30B", ci_30b), ("XiYanSQL-32B", ci_xiyan)) if ci[1] < 0]
    decision = "off" if harmed else "on"
    reason = (
        f"dev A/B, mean per-case change in correct candidate share (strict v3, {EXPECTED_CASES} "
        f"ANSWER cases, N=5, linked minus unlinked, 95% bootstrap CI over cases): Qwen3-30B "
        f"{mean_30b:+.4f} [{ci_30b[0]:+.4f}, {ci_30b[1]:+.4f}], XiYanSQL-32B {mean_xiyan:+.4f} "
        f"[{ci_xiyan[0]:+.4f}, {ci_xiyan[1]:+.4f}]; rule: on unless either CI lies entirely below "
        f"zero -> {decision}" + (f" ({' and '.join(harmed)} harmed)" if harmed else "")
    )
    return decision, reason


def _evaluate(evidence_path: Path, db: str) -> dict:
    """The decision metric, plus pass@1 and pass@N as descriptive figures only."""
    from evals import entity_link_eval as E
    from evals.rescore_v2 import Gold, score_bakeoff

    pools = score_bakeoff(E.load(evidence_path), Gold(db))
    base = [p for p in pools if p.profile == "baseline"]
    linked = [p for p in pools if p.profile == "linked"]
    diffs = case_share_diffs(base, linked)
    if len(diffs) != EXPECTED_CASES:
        raise ValueError(f"{evidence_path}: {len(diffs)} cases, expected {EXPECTED_CASES}")
    values = list(diffs.values())
    r = E.compare(base, linked, "v3")
    return {
        "mean": sum(values) / len(values),
        "ci": bootstrap_ci(values),
        "descriptive": {
            "pass_1": (r["pass_1"]["base"], r["pass_1"]["linked"]),
            "pass_1_gained_lost": (len(r["pass_1"]["gained"]), len(r["pass_1"]["lost"])),
            "pass_n": (r["pass_n"]["base"], r["pass_n"]["linked"]),
            "pass_n_gained_lost": (len(r["pass_n"]["gained"]), len(r["pass_n"]["lost"])),
            "candidates": r["candidates"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Apply the pre-registered entity-linking rule to the dev A/B."
    )
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument(
        "--qwen3-30b", type=Path, default=REPO / "reports" / "entity_link_ab_qwen3_30b.jsonl"
    )
    ap.add_argument(
        "--xiyan", type=Path, default=REPO / "reports" / "entity_link_ab_xiyan_32b.jsonl"
    )
    args = ap.parse_args(argv)
    a, b = _evaluate(args.qwen3_30b, args.db), _evaluate(args.xiyan, args.db)
    decision, reason = apply_rule(a["ci"], b["ci"], a["mean"], b["mean"])
    for name, r in (("Qwen3-30B", a), ("XiYanSQL-32B", b)):
        print(f"descriptive only, {name}: {r['descriptive']}")
    print(f"decision: {decision}\nreason: {reason}")
    print(
        "Record both in evals/heldout_config.json (entity_link.decision, entity_link.reason), "
        "the protocol and DECISIONS.md, in one commit, before any held-out run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
