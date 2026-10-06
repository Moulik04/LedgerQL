"""What a run ran on: the versions and inputs its figures depend on besides the code.

Configuration H pins `ledgerql/` by tree hash, but the same code behaves differently on a
different SQL parser, a different DuckDB or a different model server. This reports what was
actually resolved, as one JSON object for `run_meta.json`:

    python -m evals.run_env [--server-python <the vLLM venv's python>] [--db data/ledgerql.duckdb]

- `packages`: the installed versions of the packages the evaluating process's results depend on
  (`duckdb` executes every query, `sqlglot` parses every candidate), beside `locked`, the versions
  `uv.lock` names for them, and `uv_lock_sha256`.
- `server`: the model server's packages (`vllm`, `transformers`, `torch`). On the cluster the
  server has its own environment, installed without a lock file, so its versions are read from
  that environment's interpreter.
- `settings`: the environment variables that override a pipeline default, as set or unset.

Reading the environment never fails a run: what cannot be read is recorded as such. Whether a
held-out run may proceed is decided elsewhere (`evals/measurement_pin.py`), which compares all of
this with the pin.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK_PATH = REPO / "uv.lock"

EVAL_PACKAGES = ("duckdb", "sqlglot")
SERVER_PACKAGES = ("vllm", "transformers", "torch")
# Variables that override a pipeline default when set (the defaults are in `ledgerql/`, so the
# configuration's tree hash pins them only while these are unset). The model and the backend are
# given to the run itself and are in `run_meta.json` already.
SETTINGS = (
    "OLLAMA_TEMPERATURE",
    "OLLAMA_CONSENSUS_TEMPERATURE",
    "OLLAMA_SEED",
    "LEDGERQL_ENTITY_LINK",
    "LEDGERQL_ROW_LIMIT",
    "LEDGERQL_QUERY_TIMEOUT_SECONDS",
    "LEDGERQL_OFFLINE_TIMEOUT_SECONDS",
    "LEDGERQL_DB_PATH",
)

_VERSIONS_SNIPPET = (
    "import importlib.metadata as m, json, platform, sys\n"
    "out = {'python': platform.python_version()}\n"
    "for name in sys.argv[1:]:\n"
    "    try:\n"
    "        out[name] = m.version(name)\n"
    "    except m.PackageNotFoundError:\n"
    "        out[name] = None\n"
    "print(json.dumps(out))\n"
)


def sha256_file(path) -> str | None:
    """The SHA-256 of a file's bytes, or None if there is no such file."""
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed(packages=EVAL_PACKAGES) -> dict[str, str | None]:
    """The version of each package in this interpreter's environment (None: not installed)."""
    out = {}
    for name in packages:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = None
    return out


def locked(packages=EVAL_PACKAGES, lock_path=LOCK_PATH) -> dict[str, str | None]:
    """The version `uv.lock` names for each package (None: not in the lock, or no lock)."""
    lock_path = Path(lock_path)
    if not lock_path.is_file():
        return {name: None for name in packages}
    by_name = {p["name"]: p.get("version") for p in tomllib.loads(lock_path.read_text())["package"]}
    return {name: by_name.get(name) for name in packages}


def server_versions(python: str | None, packages=SERVER_PACKAGES, timeout: float = 120) -> dict:
    """The model server's package versions, read by its own interpreter. Never raises."""
    if not python:
        return {"unavailable": "no server interpreter was given (--server-python)"}
    try:
        done = subprocess.run(
            [python, "-c", _VERSIONS_SNIPPET, *packages],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return {"interpreter": str(python), **json.loads(done.stdout)}
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"interpreter": str(python), "unavailable": f"{type(e).__name__}: {e}"[:300]}


def describe(server_python: str | None = None, db_path: str | None = None) -> dict:
    out = {
        "python": platform.python_version(),
        "packages": installed(),
        "locked": locked(),
        "uv_lock_sha256": sha256_file(LOCK_PATH),
        "server": server_versions(server_python),
        "settings": {name: os.environ.get(name) for name in SETTINGS},
    }
    if db_path:
        out["database_sha256"] = sha256_file(db_path)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server-python", help="the interpreter of the model server's environment")
    ap.add_argument("--db", help="also record this database file's SHA-256")
    args = ap.parse_args(argv)
    print(json.dumps(describe(args.server_python, args.db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
