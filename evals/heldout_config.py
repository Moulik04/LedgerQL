"""The pinned held-out headline configuration (evals/HELDOUT_PROTOCOL.md 6a).

`heldout_config.json` is an append-only list of declarations. The active one names the code
(`code_commit`, and `ledgerql_tree`: the git tree hash of `ledgerql/`, which changes if and only
if the pipeline code changes), the models, the job scripts, the settings, and how the
entity-linking setting is decided. **Any later change under `ledgerql/` is a new configuration**
that needs its own declaration. A held-out run (`run_eval` or `gen_only_eval` on a
`heldout*.jsonl` file) is refused unless the code tree and the linker environment match the
active declaration and the linker decision has been recorded. That decision is made from the dev
A/B and recorded before any held-out run; it is never chosen from held-out results.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from evals.scoring import FrozenGoldError

CONFIG_PATH = Path(__file__).resolve().parent / "heldout_config.json"
REPO = Path(__file__).resolve().parent.parent


def load(path: Path = CONFIG_PATH) -> list[dict]:
    return json.loads(Path(path).read_text())


def active(decls: list[dict] | None = None) -> dict:
    decls = decls if decls is not None else load()
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


def apply_rule(net_30b: int, net_xiyan: int) -> tuple[str, str]:
    """The entity-linking decision rule, exactly as fixed in the protocol before the dev A/B result:
    on iff Qwen3-30B's net pass@1 gain is at least +2 cases and XiYanSQL-32B's is not negative."""
    on = net_30b >= 2 and net_xiyan >= 0
    reason = (
        f"dev A/B net pass@1 (strict v3, 50 ANSWER cases, N=5): Qwen3-30B {net_30b:+d}, "
        f"XiYanSQL-32B {net_xiyan:+d}; rule: on iff 30B >= +2 and XiYan >= 0 -> "
        f"{'on' if on else 'off'}"
    )
    return ("on" if on else "off"), reason


def _net_pass_1(evidence_path: Path, db: str) -> int:
    from evals import entity_link_eval as E
    from evals.rescore_v2 import Gold, score_bakeoff

    pools = score_bakeoff(E.load(evidence_path), Gold(db))
    base = [p for p in pools if p.profile == "baseline"]
    linked = [p for p in pools if p.profile == "linked"]
    r = E.compare(base, linked, "v3")["pass_1"]
    return len(r["gained"]) - len(r["lost"])


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
    decision, reason = apply_rule(
        _net_pass_1(args.qwen3_30b, args.db), _net_pass_1(args.xiyan, args.db)
    )
    print(f"decision: {decision}\nreason: {reason}")
    print(
        "Record both in evals/heldout_config.json (entity_link.decision, entity_link.reason), "
        "the protocol and DECISIONS.md, in one commit, before any held-out run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
