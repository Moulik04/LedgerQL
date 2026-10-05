"""The pin on the measurement: the code that turns a held-out run into figures, and the
environment it runs in (evals/HELDOUT_PROTOCOL.md 6a).

Configuration H pins the pipeline (`ledgerql/`, by tree hash). The figures also depend on what is
not under `ledgerql/`: the scorer and comparator, the auditor, the `answer_must_state` grader and
its patterns, the prompts of the generation-only runs, the schema text every prompt carries, the
job scripts, and the versions of the packages that parse and execute SQL. A change to any of them
after held-out results exist is a measurement chosen with those results in view, exactly as a
pipeline change would be a configuration chosen with them in view.

So before any held-out run the listed files and `uv.lock` are hashed into
`evals/measurement_pin.json`, and a held-out run is refused unless a pin exists and every file,
`uv.lock` and the installed `duckdb` and `sqlglot` match it. The pin is its own file: the
configuration declarations (`heldout_config.json`) are not touched by it.

    python -m evals.measurement_pin draft    # the list, for review; writes nothing
    python -m evals.measurement_pin check    # does the working tree match the pin?
    python -m evals.measurement_pin apply --approved-by MJ --why "..."   # record the pin

`PINNED` is the list. It is checked against the code: every module a held-out entry point
imports, directly or not, must be in it, and every other `evals/*.py` must be in `NOT_PINNED`
with its reason, so a file can be left out only by saying why.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

from evals import run_env
from evals.scoring import FrozenGoldError

REPO = Path(__file__).resolve().parent.parent
PIN_PATH = Path(__file__).resolve().parent / "measurement_pin.json"

# The commands that produce a held-out figure. What they import is pinned with them.
ENTRY_POINTS = {
    "evals/run_eval.py": "the pipeline runs: figures 2 and 3, accuracy, assumption cases",
    "evals/gen_only_eval.py": "the generation-only runs behind P1, P2 and P3",
    "evals/audit_vs_verify.py": "figure 1: the draft rate, its split, the audit",
    "evals/summarize_run.py": "a returned run re-scored under the frozen gold",
    "evals/entity_link_eval.py": "P1 and P2: linked against unlinked",
    "evals/heldout_gold_check.py": "the gold check that must pass before the set is frozen",
    "evals/heldout_config.py": "the configuration pin; the bootstrap intervals",
    "evals/measurement_pin.py": "this pin",
}

PINNED = {
    **ENTRY_POINTS,
    "evals/run_env.py": "reads the hashes and versions the pin compares",
    # scorer and comparator
    "evals/scoring.py": "does this result answer this case; the gold freeze check",
    "evals/gold_v2.py": "comparator rules V1 to V6",
    "evals/gold_v3.py": "comparator rules V5 revised and V7 to V9",
    "evals/passn_scoring.py": "pass@1 and pass@N over the candidates",
    "evals/offline_exec.py": "how a candidate's SQL is executed for scoring",
    # metrics
    "evals/abstain_scoring.py": "abstain precision and recall, the assumption-case split",
    "evals/confidently_wrong.py": "figure 2",
    "evals/repair_scoring.py": "imported by run_eval (repair is off in H)",
    "evals/rescore_v2.py": "strict and relaxed scoring; the agree-policy table (figure 4)",
    "evals/pairwise_agreement.py": "whether two models' results agree (figure 4, P4)",
    "evals/signal_precheck.py": "cross-model agreement (figure 4, P4)",
    "evals/replay_repair_off.py": "imported by rescore_v2: headline metrics from records",
    "evals/replay_year_rule.py": "imported by rescore_v2",
    "evals/bakeoff_evidence.py": "reads the candidates of a generation-only run (P3)",
    "evals/pipeline_acceptance.py": "imported by audit_vs_verify: loads a run's records",
    # the independent auditor
    "evals/number_audit.py": "the auditor behind figure 1",
    "evals/NUMBER_AUDIT_SPEC.md": "the specification the auditor is written from",
    # the answer_must_state grader
    "evals/must_state.py": "the grader behind 'assumption stated'",
    "evals/must_state_patterns.json": "its patterns, and which items the judge decides",
    # what the model is asked, outside ledgerql/
    "evals/gen_prompts.py": "the prompts of the generation-only runs (P1, P2, P3)",
    "docs/schema.md": "the schema text in every generation prompt",
    # the jobs
    "scripts/bridges2/run_model_eval.sh": "the job body: server flags and the eval command",
    "scripts/bridges2/assert_commit.sh": "the commit check every job runs first",
    "scripts/bridges2/submit.sh": "pull, verify, submit",
    "scripts/bridges2/run_qwen3_coder_30b_fp16.sbatch": "H's primary model",
    "scripts/bridges2/run_qwen25_coder_32b_awq.sbatch": "H's policy partner",
    "scripts/bridges2/run_qwen3_coder_30b_entitylink.sbatch": "P1",
    "scripts/bridges2/run_xiyansql_32b_entitylink.sbatch": "P2",
    "scripts/bridges2/run_qwen3_coder_30b_genonly.sbatch": "P3",
    "scripts/bridges2/run_qwen25_coder_32b_awq_genonly.sbatch": "P3",
    "scripts/bridges2/run_xiyansql_32b_genonly.sbatch": "P3",
}

_DEV_ONLY = "a development-set diagnostic; no held-out entry point imports it"
NOT_PINNED = {
    "evals/check_replay.py": _DEV_ONLY,
    "evals/colocation_audit.py": "reads the cluster's accounting, not results",
    "evals/comparator_audit.py": _DEV_ONLY,
    "evals/diagnose_abstains.py": _DEV_ONLY,
    "evals/entity_upper_bound.py": _DEV_ONLY,
    "evals/gold_audit.py": _DEV_ONLY,
    "evals/heldout_slots.py": "drew the slot sheet, which is pinned by its own hash",
    "evals/nodata_audit.py": _DEV_ONLY,
    "evals/pool_experiment.py": _DEV_ONLY,
    "evals/replay_derived.py": _DEV_ONLY,
    "evals/replay_frame.py": _DEV_ONLY,
    "evals/replay_refusals.py": _DEV_ONLY,
    "evals/replay_verifier.py": "replays two verifier revisions on stored drafts; a regression "
    "check for a new configuration, not a figure",
    "evals/validate_gold.py": "validates the development gold, which is pinned by its own hash",
    "evals/year_audit.py": "the year-only diagnostic the auditor replaced; it imports the verifier",
}


def evals_imports(repo: Path = REPO) -> dict[str, set[str]]:
    """For each `evals/*.py`, the `evals/*.py` files it imports (anywhere in the file, so an
    import inside a function counts)."""
    files = {p.stem: f"evals/{p.name}" for p in sorted((repo / "evals").glob("*.py"))}
    graph: dict[str, set[str]] = {}
    for stem, rel in files.items():
        names: set[str] = set()
        for node in ast.walk(ast.parse((repo / rel).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "evals":
                    names |= {a.name for a in node.names}
                elif node.module.startswith("evals."):
                    names.add(node.module.split(".")[1])
            elif isinstance(node, ast.Import):
                names |= {a.name.split(".")[1] for a in node.names if a.name.startswith("evals.")}
        graph[rel] = {files[n] for n in names if n in files and n != stem}
    return graph


def import_closure(roots, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    todo = [r for r in roots if r in graph]
    while todo:
        rel = todo.pop()
        if rel not in seen:
            seen.add(rel)
            todo += graph[rel]
    return seen


def file_hashes(paths=None, repo: Path = REPO) -> dict[str, str | None]:
    return {
        rel: run_env.sha256_file(repo / rel) for rel in sorted(PINNED if paths is None else paths)
    }


def draft(repo: Path = REPO) -> dict:
    """What a pin applied now would record. Nothing is written."""
    return {
        "files": file_hashes(repo=repo),
        "environment": {
            "uv_lock_sha256": run_env.sha256_file(repo / "uv.lock"),
            "locked": run_env.locked(lock_path=repo / "uv.lock"),
        },
    }


def load_pins(path: Path = PIN_PATH) -> list[dict]:
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else []


def active_pin(pins: list[dict] | None = None) -> dict | None:
    pins = load_pins() if pins is None else pins
    live = [p for p in pins if p["status"] == "active"]
    if len(live) > 1:
        raise ValueError(f"at most one measurement pin may be active, found {len(live)}")
    return live[0] if live else None


def problems(pin: dict, repo: Path = REPO, installed: dict | None = None) -> list[str]:
    """Every way the working tree and the environment differ from the pin."""
    out = []
    for rel, pinned in sorted(pin["files"].items()):
        actual = run_env.sha256_file(repo / rel)
        if actual is None:
            out.append(f"{rel} is pinned and does not exist")
        elif actual != pinned:
            out.append(f"{rel} differs from the pin")
    env = pin["environment"]
    if run_env.sha256_file(repo / "uv.lock") != env["uv_lock_sha256"]:
        out.append("uv.lock differs from the pin")
    installed = run_env.installed(tuple(env["locked"])) if installed is None else installed
    for name, version in sorted(env["locked"].items()):
        if installed.get(name) != version:
            out.append(
                f"{name} {installed.get(name)} is installed and the pinned uv.lock names {version}"
            )
    return out


def require_pinned(path, pins: list[dict] | None = None, repo: Path = REPO) -> None:
    """Refuse a held-out run unless the measurement is pinned and matches its pin. Any other gold
    file is not checked."""
    if not Path(path).name.startswith("heldout"):
        return
    pin = active_pin(pins)
    if pin is None:
        raise FrozenGoldError(
            "the measurement code and environment are not pinned: record the pin "
            "(python -m evals.measurement_pin apply) before any held-out run"
        )
    found = problems(pin, repo)
    if found:
        raise FrozenGoldError(
            f"the measurement differs from pin {pin['id']}: " + "; ".join(found) + ". A change "
            "to the measurement after the pin needs a new pin, declared before any held-out run"
        )


def apply(approved_by: str, why: str, path: Path = PIN_PATH, repo: Path = REPO) -> dict:
    """Record a pin of the working tree as it is. An earlier pin is kept, marked superseded."""
    pins = load_pins(path)
    new = {
        "id": f"M{len(pins) + 1}",
        "status": "active",
        "declared": dt.date.today().isoformat(),
        "approved_by": approved_by,
        "why": why,
        **draft(repo),
    }
    missing = [rel for rel, digest in new["files"].items() if digest is None]
    if missing or new["environment"]["uv_lock_sha256"] is None:
        raise ValueError(f"cannot pin files that do not exist: {missing or ['uv.lock']}")
    for old in pins:
        if old["status"] == "active":
            old["status"], old["superseded_by"] = "superseded", new["id"]
    Path(path).write_text(json.dumps([*pins, new], indent=1) + "\n")
    return new


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["draft", "check", "apply"])
    ap.add_argument("--approved-by")
    ap.add_argument("--why")
    args = ap.parse_args(argv)
    if args.command == "draft":
        d = draft()
        print(f"{len(d['files'])} files, and uv.lock ({d['environment']['locked']}):\n")
        for rel in sorted(PINNED):
            print(f"  {rel}\n      {PINNED[rel]}")
        print(f"\nNot pinned ({len(NOT_PINNED)}), and why:\n")
        for rel in sorted(NOT_PINNED):
            print(f"  {rel}\n      {NOT_PINNED[rel]}")
        return 0
    if args.command == "check":
        pin = active_pin()
        if pin is None:
            print("no measurement pin is recorded: held-out runs are refused")
            return 1
        found = problems(pin)
        print("\n".join(found) if found else f"the working tree matches pin {pin['id']}")
        return 1 if found else 0
    if not (args.approved_by and args.why):
        ap.error("apply needs --approved-by and --why")
    new = apply(args.approved_by, args.why)
    print(f"recorded pin {new['id']}: {len(new['files'])} files and uv.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
