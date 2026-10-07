"""The pin on the measurement: the code that turns a held-out run into figures, and the
environment it runs in (evals/HELDOUT_PROTOCOL.md 6a).

Configuration H pins the pipeline (`ledgerql/`, by tree hash). The figures also depend on what is
not under `ledgerql/`: the scorer and comparator, the auditor, the `answer_must_state` grader and
its patterns, the prompts of the generation-only runs, the schema text every prompt carries, the
job scripts, and the versions of the packages that parse and execute SQL. A change to any of them
after held-out results exist is a measurement chosen with those results in view, exactly as a
pipeline change would be a configuration chosen with them in view.

So before any held-out run the listed files and `uv.lock` are hashed into
`evals/measurement_pin.json`, with the database's hash and the model server's versions as the
cluster reports them. The pin is its own file: the configuration declarations
(`heldout_config.json`) are not touched by it.

    python -m evals.measurement_pin draft    # the list, for review; writes nothing
    python -m evals.measurement_pin check [--db data/ledgerql.duckdb]   # does this tree match?
    python -m evals.measurement_pin apply --approved-by MJ --why "..." --cluster-env <file>

`<file>` is what `python -m evals.run_env --server-python ... --db ...` printed on the cluster
(docs/bridges2.md). The pin is refused if that record disagrees with this tree.

**A held-out run is refused** (`require_pinned`) unless a pin exists and all of these match it:
every listed file and `uv.lock`; the installed `duckdb` and `sqlglot`; the database file; the model
server's `vllm`, `transformers` and `torch`; the revision of the weights it downloaded
(`MODEL_REVISIONS`); and the generation settings (`SETTINGS`), with no variable that overrides a
default set in the environment. Whatever can change an output is
compared. What legitimately varies between runs (job id, node, port, time) is only recorded.

**The judge is refused** (`require_judge`) once a pin exists, unless the Ollama that will be asked
is the pinned version (`OLLAMA_VERSION`) and serves the judge model at the pinned digest
(`JUDGE_DIGESTS`): the local model that decides the `primary: judge` rubric items is asked on the
laptop, after a run, and is as much a part of the measurement as a pattern.

**An offline figure command is refused** (`require_unchanged`) once a pin exists, if the files,
`uv.lock`, the installed packages or the database it is given differ from it. It hashes the
working tree, so an edit that was never committed is refused too.

`PINNED` is the list. It is checked against the code: every module a held-out entry point
imports, directly or not, must be in it, and every other `evals/*.py` must be in `NOT_PINNED`
with its reason, so a file can be left out only by saying why.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
from pathlib import Path

from evals import run_env
from evals.scoring import FrozenGoldError

REPO = Path(__file__).resolve().parent.parent
PIN_PATH = Path(__file__).resolve().parent / "measurement_pin.json"
DEFAULT_DB = "data/ledgerql.duckdb"

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


# What a held-out run generates with. Configuration H3 declares the pipeline's models, the number
# of candidates, the candidate temperature, the seed and the linker (a test holds these to it); the
# answer temperature is the pipeline's default at H3's tree; the generation-only values are
# protocol section 6's (N=5, temperature 0.7, seeds from 42) and that eval's token limit. A list
# is the set of allowed values. The pipeline sends no token limit of its own: a reply is bounded by
# the server's context length, which each job file sets (MAX_MODEL_LEN).
SETTINGS = {
    "pipeline": {
        "model": ["Qwen/Qwen3-Coder-30B-A3B-Instruct", "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"],
        "backend": "vllm",
        "candidates": 5,
        "consensus_temperature": 0.7,
        "temperature": 0.2,
        "seed": 42,
        "entity_link": True,
    },
    "gen_only": {
        "model": [
            "Qwen/Qwen3-Coder-30B-A3B-Instruct",
            "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
            "XGenerationLab/XiYanSQL-QwenCoder-32B-2504",
        ],
        "candidates": 5,
        "temperature": 0.7,
        "max_tokens": 2048,
        "seed": 42,
    },
}

# The commit of each model's Hugging Face repository that a held-out run is served. Each was the
# head of `main` when read on 2026-10-05, and each repository's latest commit is older than the
# first cluster run (2026-09-14), so these are also the weights every development run was served
# (no job ever named a revision, so each got `main`). Latest commits: the 30B 2025-12-03, the
# 32B AWQ 2024-11-18, XiYanSQL 2025-12-04. The pinned job files download exactly these.
MODEL_REVISIONS = {
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": "b2cff646eb4bb1d68355c01b18ae02e7cf42d120",
    "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ": "1ed0a6145da0ce550c628e8e8b678f51e695995d",
    "XGenerationLab/XiYanSQL-QwenCoder-32B-2504": "50c30a65a388e9cdc39965b76c30cdbe427a2365",
}

# The local judge that decides the `primary: judge` rubric items (`evals/must_state.py`), by the
# digest Ollama reports for the model it serves (`ollama list` shows its first twelve characters).
# Read on 2026-10-07 from the laptop's Ollama, whose copy was pulled on 2026-06-14, before the
# grader existed: every judge vote in a development report was cast by this model.
JUDGE_DIGESTS = {
    "llama3.1:8b": "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e",
}
# The Ollama that serves it, as its own `/api/version` reports (read on 2026-10-07): the same
# weights can answer differently under another runtime, as under another vLLM.
OLLAMA_VERSION = "0.30.8"

# The pinned commands that compute a figure from stored records, on the laptop, after a run. Each
# opens with the check named here (a test holds them to it).
_WITH_DB, _NO_DB = (
    "measurement_pin.require_unchanged(args.db)",
    "measurement_pin.require_unchanged()",
)
OFFLINE_COMMANDS = {
    "evals/audit_vs_verify.py": _WITH_DB,
    "evals/summarize_run.py": _WITH_DB,
    "evals/entity_link_eval.py": _WITH_DB,
    "evals/rescore_v2.py": _WITH_DB,
    "evals/passn_scoring.py": _WITH_DB,
    "evals/signal_precheck.py": _WITH_DB,
    "evals/pipeline_acceptance.py": _WITH_DB,
    "evals/pairwise_agreement.py": _NO_DB,
}
NOT_OFFLINE_COMMANDS = {
    "evals/heldout_config.py": "applies the linker rule to the dev A/B; the decision is recorded",
    "evals/heldout_gold_check.py": "checks the gold before the set is frozen; computes no figure",
    "evals/measurement_pin.py": "the pin's own command line (draft, check, apply)",
    "evals/run_env.py": "prints the environment; computes no figure",
    "evals/bakeoff_evidence.py": "packs candidates into the evidence file; scores nothing",
    "evals/must_state.py": "builds the label sheets and the grader's agreement, before the pin",
    "evals/gold_v2.py": "rebuilds the development gold v2 from v1; scores nothing",
    "evals/gold_v3.py": "rebuilds the development gold v3, which is frozen by its own hash",
    "evals/replay_repair_off.py": "a counterfactual on development reports, scored against gold v1",
    "evals/replay_year_rule.py": "a counterfactual on development reports, scored against gold v1",
}

SETUP_ENV = "scripts/bridges2/setup_env.sh"


def setup_vllm_version(repo: Path = REPO) -> str | None:
    """The vLLM version `setup_env.sh` installs (None: it names none)."""
    path = repo / SETUP_ENV
    found = re.search(r"^VLLM_VERSION=(\S+)$", path.read_text(), re.M) if path.is_file() else None
    return found.group(1).strip("\"'") if found else None


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
    """What a pin applied now would record from this tree. Nothing is written. The database's hash
    and the server's versions come from the cluster's record when the pin is applied."""
    return {
        "files": file_hashes(repo=repo),
        "environment": {
            "uv_lock_sha256": run_env.sha256_file(repo / "uv.lock"),
            "locked": run_env.locked(lock_path=repo / "uv.lock"),
        },
        "settings": json.loads(json.dumps(SETTINGS)),
        "models": dict(MODEL_REVISIONS),
        "judge": dict(JUDGE_DIGESTS),
        "ollama": OLLAMA_VERSION,
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


def problems(
    pin: dict, repo: Path = REPO, installed: dict | None = None, *, db=None, server=None
) -> list[str]:
    """Every way the working tree and the environment differ from the pin. The database is
    compared if `db` is given, and the model server if `server` is (its versions as
    `run_env.server_versions` read them)."""
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
    if db is not None:
        actual = run_env.sha256_file(db)
        if actual is None:
            out.append(f"the database {db} does not exist")
        elif actual != env["database_sha256"]:
            out.append(f"the database {db} differs from the pin")
    if server is not None:
        if "unavailable" in server:
            out.append(f"the model server's versions could not be read ({server['unavailable']})")
        else:
            out += [
                f"the model server has {name} {server.get(name)} and the pin names {version}"
                for name, version in sorted(env["server"].items())
                if server.get(name) != version
            ]
    return out


def override_problems(environ) -> list[str]:
    """The variables set in `environ` that override a default. A held-out run takes every setting
    from the declaration, so one of these left exported in the submitting shell stops it. The
    linker's variable is the exception: it has to be set, and configuration H checks its value."""
    return [
        f"{name} is set in the environment ({environ[name]!r}): a held-out run takes its "
        "settings from the declaration, not from the submitting shell; unset it"
        for name in sorted(run_env.SETTINGS)
        if name != "LEDGERQL_ENTITY_LINK" and name in environ
    ]


def settings_problems(declared: dict, mode: str, settings: dict) -> list[str]:
    """Every generation setting of this run (`settings`, as the run resolved it) that is not the
    declared one for its mode."""
    out = []
    for name, want in declared[mode].items():
        got = settings.get(name)
        if not (got in want if isinstance(want, list) else got == want):
            out.append(f"{name} is {got!r} and the declared {mode} setting is {want!r}")
    return out


def revision_problems(pinned: dict, model: str, model_cache) -> list[str]:
    """Why the weights in the job's own download cache (`model_cache`, its `HF_HOME`) are not the
    pinned revision of `model`, and only that one."""
    want = pinned.get(model)
    if want is None:
        return [f"no revision is pinned for {model}"]
    served = run_env.served_revisions(model, model_cache)
    if served is None:
        return [
            f"the downloaded weights of {model} were not found under {model_cache} (--model-cache)"
        ]
    if served != [want]:
        return [f"{model} was downloaded at revision {', '.join(served)} and the pin names {want}"]
    return []


def served_digest(client, model: str) -> str | None:
    """The digest the Ollama behind `client` reports for `model` (None: it does not have it)."""
    return next((m.digest for m in client.list().models if m.model == model), None)


def served_ollama_version(host: str) -> str | None:
    """The version the Ollama at `host` reports for itself (None: it could not be read)."""
    import httpx

    try:
        return httpx.get(f"{host}/api/version", timeout=10).json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def judge_problems(pin: dict, model: str, served: str | None, version: str | None) -> list[str]:
    """Why the judge `model`, served at digest `served` by Ollama `version`, is not the pinned
    judge on the pinned Ollama."""
    out = []
    if version is None:
        out.append("Ollama's version could not be read")
    elif version != pin["ollama"]:
        out.append(f"Ollama is version {version} and the pin names {pin['ollama']}")
    want = pin["judge"].get(model)
    if want is None:
        out.append(f"no digest is pinned for the judge {model}")
    elif served is None:
        out.append(f"Ollama does not have the judge {model}, so its digest cannot be read")
    elif served != want:
        out.append(
            f"the judge {model} is served at digest {served[:12]} and the pin names {want[:12]}"
        )
    return out


def _refuse(pin: dict, found: list[str]) -> None:
    if found:
        raise FrozenGoldError(
            f"the measurement differs from pin {pin['id']}: " + "; ".join(found) + ". A change "
            "to the measurement after the pin needs a new pin, declared before any held-out run"
        )


def require_pinned(
    path,
    *,
    mode: str,
    settings: dict,
    db,
    server_python: str | None,
    model_cache,
    pins: list[dict] | None = None,
    repo: Path = REPO,
    environ=None,
) -> None:
    """Refuse a held-out run unless the measurement is pinned and this run matches the pin: the
    files, the environment, the database `db`, the model server whose interpreter is
    `server_python`, the weights in the job's download cache `model_cache`, and the generation
    `settings` of a run of this `mode` ("pipeline" or "gen_only"). Any other gold file is not
    checked."""
    if not Path(path).name.startswith("heldout"):
        return
    pin = active_pin(pins)
    if pin is None:
        raise FrozenGoldError(
            "the measurement code and environment are not pinned: record the pin "
            "(python -m evals.measurement_pin apply) before any held-out run"
        )
    _refuse(
        pin,
        problems(pin, repo, db=db, server=run_env.server_versions(server_python))
        + revision_problems(pin["models"], settings.get("model"), model_cache)
        + override_problems(os.environ if environ is None else environ)
        + settings_problems(pin["settings"], mode, settings),
    )


def require_unchanged(db=None, pins: list[dict] | None = None, repo: Path | None = None) -> None:
    """Refuse to compute a figure offline on a tree that differs from the pin: a pinned file
    (committed or not), `uv.lock`, the installed packages, or the database `db` if the command
    opens one. Until a pin is recorded nothing is held, so development work is not stopped."""
    pin = active_pin(pins)
    if pin is not None:
        _refuse(pin, problems(pin, REPO if repo is None else repo, db=db))


def require_judge(model: str, client, host: str, pins: list[dict] | None = None) -> None:
    """Refuse to ask a judge that is not the pinned one: `model` must be a judge the pin names,
    and the Ollama at `host`, which `client` talks to, must be the pinned version and serve the
    model at the pinned digest. As for the offline commands, nothing is held until a pin is
    recorded."""
    pin = active_pin(pins)
    if pin is not None:
        found = judge_problems(
            pin, model, served_digest(client, model), served_ollama_version(host)
        )
        _refuse(pin, found)


def cluster_problems(record: dict, repo: Path = REPO, db=None) -> list[str]:
    """Why the cluster's record (`python -m evals.run_env --server-python ... --db ...`, run
    there) cannot be pinned with this tree."""
    out = []
    locked = run_env.locked(lock_path=repo / "uv.lock")
    if record.get("uv_lock_sha256") != run_env.sha256_file(repo / "uv.lock"):
        out.append("the cluster's uv.lock is not this tree's: pull there, uv sync, and read again")
    if record.get("packages") != locked:
        out.append(
            f"the cluster's eval environment has {record.get('packages')}; uv.lock names {locked}"
        )
    server = record.get("server") or {}
    out += [
        f"the cluster's record has no version for the model server's {name}"
        for name in run_env.SERVER_PACKAGES
        if not server.get(name)
    ]
    named = setup_vllm_version(repo)
    if server.get("vllm") and server["vllm"] != named:
        out.append(
            f"the cluster's model server has vllm {server['vllm']}; setup_env.sh installs {named}"
        )
    theirs, ours = record.get("database_sha256"), run_env.sha256_file(db)
    if theirs is None:
        out.append("the cluster's record does not state the database's hash (run it with --db)")
    elif ours is None:
        out.append(f"there is no local database at {db} to compare the cluster's with")
    elif theirs != ours:
        out.append(
            f"the cluster's database is not the local one ({theirs[:12]} there, {ours[:12]} here)"
        )
    return out


def apply(
    approved_by: str,
    why: str,
    cluster_env: dict,
    path: Path = PIN_PATH,
    repo: Path = REPO,
    db=None,
) -> dict:
    """Record a pin of the working tree as it is, with the model server's versions and the
    database's hash from the cluster's record `cluster_env`. The database the offline figures are
    computed against (`db`, here) must be the one the cluster holds. An earlier pin is kept,
    marked superseded."""
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
    found = cluster_problems(cluster_env, repo, repo / DEFAULT_DB if db is None else db)
    if found:
        raise ValueError("the cluster's record cannot be pinned: " + "; ".join(found))
    new["environment"] |= {
        "database_sha256": cluster_env["database_sha256"],
        "server": {name: cluster_env["server"][name] for name in run_env.SERVER_PACKAGES},
        "cluster_record": cluster_env,
    }
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
    ap.add_argument("--cluster-env", type=Path, help="apply: the cluster's run_env record (JSON)")
    ap.add_argument("--db", help=f"check: also compare this database; apply: default {DEFAULT_DB}")
    args = ap.parse_args(argv)
    if args.command == "draft":
        d = draft()
        print(f"{len(d['files'])} files, and uv.lock ({d['environment']['locked']}):\n")
        for rel in sorted(PINNED):
            print(f"  {rel}\n      {PINNED[rel]}")
        print(f"\nNot pinned ({len(NOT_PINNED)}), and why:\n")
        for rel in sorted(NOT_PINNED):
            print(f"  {rel}\n      {NOT_PINNED[rel]}")
        print("\nGeneration settings a held-out run must have:\n")
        for mode, declared in SETTINGS.items():
            print(f"  {mode}: {declared}")
        print("\nThe revision of each model's weights:\n")
        for model, revision in MODEL_REVISIONS.items():
            print(f"  {model}\n      {revision}")
        print(f"\nThe judge's Ollama must be version {OLLAMA_VERSION} and report this digest:\n")
        for model, digest in JUDGE_DIGESTS.items():
            print(f"  {model}\n      {digest}")
        print(
            "\nFrom the cluster's record when the pin is applied: the database's hash, and the "
            f"model server's {', '.join(run_env.SERVER_PACKAGES)} (setup_env.sh installs vllm "
            f"{setup_vllm_version()})."
        )
        return 0
    if args.command == "check":
        pin = active_pin()
        if pin is None:
            print("no measurement pin is recorded: held-out runs are refused")
            return 1
        found = problems(pin, db=args.db)
        print("\n".join(found) if found else f"the working tree matches pin {pin['id']}")
        return 1 if found else 0
    if not (args.approved_by and args.why and args.cluster_env):
        ap.error("apply needs --approved-by, --why and --cluster-env")
    try:
        new = apply(
            args.approved_by, args.why, json.loads(args.cluster_env.read_text()), db=args.db
        )
    except ValueError as e:
        print(f"not pinned: {e}")
        return 1
    env = new["environment"]
    print(
        f"recorded pin {new['id']}: {len(new['files'])} files, uv.lock, database "
        f"{env['database_sha256'][:12]}, server {env['server']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
