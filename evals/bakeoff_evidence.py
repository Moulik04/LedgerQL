"""Compact, tracked evidence for the generation-only bake-off (Task 9).

The runs themselves (`reports/runs/<job>/gen_only_<profile>.jsonl`) are gitignored
cluster output and carry every raw model reply (~2.5 MB). Everything scored from
them (pass@N, agreement, the gold audit, the v2 re-scoring) needs only each
candidate's extracted SQL and the vote's pick, so this packs exactly that into
`reports/bakeoff_candidates.jsonl`, which is tracked. The SQL is re-executed
locally, so nothing recorded here is a result: it is the input to one.

    python -m evals.bakeoff_evidence pack reports/runs       # write the tracked file
    python -m evals.bakeoff_evidence summary                 # what is in it
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

EVIDENCE_PATH = Path(__file__).resolve().parent.parent / "reports" / "bakeoff_candidates.jsonl"

# job id -> model label. 47274010 (OmniSQL-32B) produced no results; see DECISIONS.md.
RUN_MODELS = {
    "47274007": "qwen3_30b",
    "47274008": "qwen25_32b_awq",
    "47274009": "xiyan_32b",
}
PROFILES = ("current", "xiyan", "omnisql")


def pack(runs_dir: Path, run_models: dict[str, str] = RUN_MODELS) -> list[dict]:
    """One record per (model, profile, case): the N extracted SQLs in candidate order,
    the vote's pick and its agreement. Raw replies are dropped."""
    out = []
    for job, model in run_models.items():
        for profile in PROFILES:
            path = Path(runs_dir) / job / f"gen_only_{profile}.jsonl"
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                out.append(
                    {
                        "run": job,
                        "model": model,
                        "profile": profile,
                        "id": rec["id"],
                        "sqls": [c["sql"] for c in rec["candidates"]],
                        "winner_sql": rec["generated_sql"],
                        "reason_code": rec["reason_code"],
                        "agreement": rec["confidence"],
                    }
                )
    return out


def write(records: list[dict], path: Path = EVIDENCE_PATH) -> None:
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in records))


def load(path: Path = EVIDENCE_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def by_run(records: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """{(model, profile): {case id: record}}."""
    out: dict[tuple[str, str], dict[str, dict]] = {}
    for r in records:
        out.setdefault((r["model"], r["profile"]), {})[r["id"]] = r
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("runs_dir", type=Path)
    sub.add_parser("summary")
    args = ap.parse_args(argv)
    if args.cmd == "pack":
        records = pack(args.runs_dir)
        write(records)
        print(f"wrote {EVIDENCE_PATH} ({len(records)} records)")
        return 0
    records = load()
    cands = Counter(r["model"] for r in records for _ in r["sqls"])
    print(f"{len(records)} records; candidates per model: {dict(cands)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
