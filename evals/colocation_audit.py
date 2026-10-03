# ruff: noqa: E501  (report format strings are single lines)
"""Were any past runs silently served by another job's server?

Jobs share nodes and used to serve vLLM on one fixed port (fixed 2026-10-02: each job now picks a free
port and checks its server's identity). Two jobs on one node then reach each other's server. Two jobs
serving *different* models fail loudly: the wrong server answers 404 on the model name. Two jobs
serving the *same* model on one node at the same time fail silently: either server's answers are
valid for either job, with batching noise but no bias. So the audit that matters is: did any two jobs
serving the same model overlap in time on one node?

Local records cannot answer that for every batch (no start and end times survive for Sep 14 and
Sep 20), so this reads the cluster's own accounting. On the login node:

    sacct -u $USER -S 2026-09-13 -E now --format=JobID%14,JobName%28,NodeList,Start,End,State,ExitCode -P > sacct.txt

then locally:

    python -m evals.colocation_audit sacct.txt
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from itertools import combinations
from pathlib import Path

SACCT_COMMAND = (
    "sacct -u $USER -S 2026-09-13 -E now "
    "--format=JobID%14,JobName%28,NodeList,Start,End,State,ExitCode -P > sacct.txt"
)

_MODELS = (
    (re.compile(r"xiyan"), "xiyan_32b"),
    (re.compile(r"omnisql"), "omnisql_32b"),
    (re.compile(r"32b"), "qwen25_32b_awq"),
    (re.compile(r"30b"), "qwen3_30b"),
)


def model_of(job_name: str) -> str:
    """The model a ledgerql job serves, from its name (`ledgerql-gen-xiyan-link` serves XiYan)."""
    name = job_name.lower()
    if not name.startswith("ledgerql"):
        return "unknown"
    for pattern, model in _MODELS:
        if pattern.search(name):
            return model
    return "unknown"


def _time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_sacct(text: str) -> list[dict]:
    """Jobs (not steps) from `sacct -P` output, one dict each."""
    lines = [x for x in text.splitlines() if x.strip()]
    header = lines[0].split("|")
    jobs = []
    for line in lines[1:]:
        row = dict(zip(header, line.split("|"), strict=False))
        job_id = row.get("JobID", "").strip()
        if not job_id or "." in job_id:  # a step (`123.batch`), not the job
            continue
        jobs.append(
            {
                "id": job_id,
                "name": row.get("JobName", "").strip(),
                "model": model_of(row.get("JobName", "")),
                "node": row.get("NodeList", "").strip(),
                "start": _time(row.get("Start", "")),
                "end": _time(row.get("End", "")),
                "state": row.get("State", "").strip(),
                "exit": row.get("ExitCode", "").strip(),
            }
        )
    return [j for j in jobs if j["model"] != "unknown"]


def audit(jobs: list[dict]) -> dict:
    audited, unaudited = [], []
    for j in jobs:
        usable = j["start"] and j["end"] and j["node"] and "assigned" not in j["node"].lower()
        (audited if usable else unaudited).append(j)
    same, cross = [], []
    for a, b in combinations(audited, 2):
        if a["node"] != b["node"]:
            continue
        overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"])).total_seconds()
        if overlap <= 0:
            continue
        pair = {"a": a["id"], "b": b["id"], "node": a["node"], "overlap_seconds": int(overlap)}
        if a["model"] == b["model"]:
            same.append({**pair, "model": a["model"]})
        else:
            failed = any(j["state"] != "COMPLETED" or j["exit"] != "0:0" for j in (a, b))
            cross.append({**pair, "models": (a["model"], b["model"]), "a_or_b_failed": failed})
    return {"jobs": len(jobs), "same_model": same, "cross_model": cross, "unaudited": unaudited}


def render(out: dict) -> str:
    lines = [f"Audited {out['jobs'] - len(out['unaudited'])} of {out['jobs']} ledgerql jobs.", ""]
    if out["same_model"]:
        lines.append("**Same model, same node, overlapping in time (the silent case):**")
        lines += [
            f"- {p['a']} and {p['b']} ({p['model']}) on {p['node']}, {p['overlap_seconds']}s"
            for p in out["same_model"]
        ]
    else:
        lines.append("No two jobs serving the same model overlapped on one node.")
    lines.append("")
    if out["cross_model"]:
        lines.append(
            "Different models overlapping on one node (loud: the wrong server answers 404):"
        )
        lines += [
            f"- {p['a']} and {p['b']} ({p['models'][0]} / {p['models'][1]}) on {p['node']}, "
            f"{p['overlap_seconds']}s; a job failed: {p['a_or_b_failed']}"
            for p in out["cross_model"]
        ]
    if out["unaudited"]:
        lines += [
            "",
            "Not auditable (no node or no start/end recorded): "
            + ", ".join(j["id"] for j in out["unaudited"]),
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sacct_file", type=Path)
    args = ap.parse_args(argv)
    out = audit(parse_sacct(args.sacct_file.read_text()))
    print(render(out))
    return 1 if out["same_model"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
