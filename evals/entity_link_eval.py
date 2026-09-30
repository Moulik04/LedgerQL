# ruff: noqa: E501  (markdown table rows are single lines)
"""Does deterministic entity linking help the local 7B? Same prompt, seeds and temperature,
with and without the resolved-companies hint (`ledgerql/entity_link.py`), scored under
gold v1, v2 strict and v2 relaxed.

Run the two conditions with `evals.gen_only_eval` (`--entity-link` for the second), then:

    python -m evals.entity_link_eval reports/runs/local7b_baseline reports/runs/local7b_linked \
        --write reports/entity_link_7b.md

Only cases where the linker adds a hint are run: elsewhere the two prompts are byte-identical,
so the two conditions cannot differ. Numbers are over those cases. `pack` writes the compact,
tracked evidence (`reports/entity_link_7b_candidates.jsonl`: SQL and the hint, no raw replies).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.rescore_v2 import DEFAULT_DB, LABELS, VERSIONS, Gold, Pool, score_bakeoff

MODEL = "qwen25_coder_7b"
EVIDENCE_PATH = (
    Path(__file__).resolve().parent.parent / "reports" / "entity_link_7b_candidates.jsonl"
)


def pack(
    baseline_dir: Path, linked_dir: Path, profile_file: str = "gen_only_current.jsonl"
) -> list[dict]:
    out = []
    for label, d in (("baseline", baseline_dir), ("linked", linked_dir)):
        for line in (Path(d) / profile_file).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            out.append(
                {
                    "model": MODEL,
                    "profile": label,
                    "id": rec["id"],
                    "sqls": [c["sql"] for c in rec["candidates"]],
                    "winner_sql": rec["generated_sql"],
                    "reason_code": rec["reason_code"],
                    "agreement": rec["confidence"],
                    "entity_hint": rec.get("entity_hint", ""),
                }
            )
    return out


def pack_run_dir(run_dir: Path, model: str, profile: str = "omnisql") -> list[dict]:
    """A Bridges-2 A/B job writes both conditions into one directory: `gen_only_<profile>.jsonl`
    (baseline) and `gen_only_<profile>_linked.jsonl` (with `--entity-link`)."""
    out = []
    for label, name in (
        ("baseline", f"gen_only_{profile}.jsonl"),
        ("linked", f"gen_only_{profile}_linked.jsonl"),
    ):
        for line in (Path(run_dir) / name).read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            out.append(
                {
                    "model": model,
                    "profile": label,
                    "id": rec["id"],
                    "sqls": [c["sql"] for c in rec["candidates"]],
                    "winner_sql": rec["generated_sql"],
                    "reason_code": rec["reason_code"],
                    "agreement": rec["confidence"],
                    "entity_hint": rec.get("entity_hint", ""),
                }
            )
    return out


def load(path: Path = EVIDENCE_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def compare(base: list[Pool], linked: list[Pool], version: str) -> dict:
    """Case-level and candidate-level differences, linked minus baseline, under one version."""
    b = {p.id: p for p in base}
    k = {p.id: p for p in linked}
    ids = sorted(set(b) & set(k))

    def metric(getter):
        bs = {i: getter(b[i]) for i in ids}
        ks = {i: getter(k[i]) for i in ids}
        return {
            "base": sum(bs.values()),
            "linked": sum(ks.values()),
            "gained": [i for i in ids if ks[i] and not bs[i]],
            "lost": [i for i in ids if bs[i] and not ks[i]],
        }

    cands = {"base": 0, "linked": 0, "n": 0, "gained": 0, "lost": 0}
    empty = {"base": 0, "linked": 0}
    for i in ids:
        for cb, ck in zip(b[i].cands, k[i].cands, strict=True):
            cands["n"] += 1
            cands["base"] += cb.verdict[version]
            cands["linked"] += ck.verdict[version]
            cands["gained"] += ck.verdict[version] and not cb.verdict[version]
            cands["lost"] += cb.verdict[version] and not ck.verdict[version]
            empty["base"] += cb.rows == []
            empty["linked"] += ck.rows == []
    return {
        "cases": len(ids),
        "pass_1": metric(lambda p: p.pass_at_1(version)),
        "pass_n": metric(lambda p: p.pass_at_n(version)),
        "candidates": cands,
        "empty": empty,
    }


LOCAL_7B_TITLE = "# Entity linking on the local 7B (qwen2.5-coder:7b, `current` prompt)"
LOCAL_7B_INTRO = (
    "{n} cases where the linker adds a hint (elsewhere the prompts are identical); N=5, "
    "temperature 0.7, seeds 42-46 in both conditions; `evals/entity_link_eval.py`. "
    "Linked minus baseline."
)


def render(
    base: list[Pool],
    linked: list[Pool],
    title: str = LOCAL_7B_TITLE,
    intro: str = LOCAL_7B_INTRO,
) -> str:
    n = len({p.id for p in base})
    lines = [
        title,
        "",
        intro.format(n=n),
        "",
        "| gold | pass@1 base -> linked | cases gained / lost | pass@N base -> linked | cases gained / lost | correct candidates base -> linked (of 5 per case) | gained / lost |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in VERSIONS:
        r = compare(base, linked, v)
        c = r["candidates"]
        lines.append(
            f"| {LABELS[v]} | {r['pass_1']['base']} -> {r['pass_1']['linked']} of {r['cases']} "
            f"| +{len(r['pass_1']['gained'])} / -{len(r['pass_1']['lost'])} "
            f"| {r['pass_n']['base']} -> {r['pass_n']['linked']} "
            f"| +{len(r['pass_n']['gained'])} / -{len(r['pass_n']['lost'])} "
            f"| {c['base']} -> {c['linked']} of {c['n']} | +{c['gained']} / -{c['lost']} |"
        )
    r = compare(base, linked, "v3")
    lines += [
        "",
        f"Candidates returning no rows (the name-literal failure): {r['empty']['base']} -> "
        f"{r['empty']['linked']} of {r['candidates']['n']}.",
        "",
        f"v3 strict pass@1 gained: {r['pass_1']['gained']}; lost: {r['pass_1']['lost']}.",
        f"v3 strict pass@N gained: {r['pass_n']['gained']}; lost: {r['pass_n']['lost']}.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("baseline", type=Path, nargs="?")
    ap.add_argument("linked", type=Path, nargs="?")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--write", type=Path)
    ap.add_argument("--run-dir", type=Path, help="a Bridges-2 A/B run directory (both conditions)")
    ap.add_argument("--model", help="model label for --run-dir, e.g. qwen3_30b")
    ap.add_argument("--profile", default="omnisql")
    ap.add_argument(
        "--pack-to", type=Path, help="where --run-dir writes the compact tracked evidence"
    )
    args = ap.parse_args(argv)
    if args.run_dir:
        if not args.model:
            ap.error("--run-dir needs --model")
        evidence = pack_run_dir(args.run_dir, args.model, args.profile)
        if args.pack_to:
            args.pack_to.write_text("".join(json.dumps(r) + "\n" for r in evidence))
    elif args.baseline and args.linked:
        evidence = pack(args.baseline, args.linked)
        EVIDENCE_PATH.write_text("".join(json.dumps(r) + "\n" for r in evidence))
    else:
        evidence = load()
    pools = score_bakeoff(evidence, Gold(args.db))
    base = [p for p in pools if p.profile == "baseline"]
    linked = [p for p in pools if p.profile == "linked"]
    if args.run_dir:
        hinted = sum(bool(r["entity_hint"]) for r in evidence if r["profile"] == "linked")
        text = render(
            base,
            linked,
            f"# Entity linking A/B: {args.model}, `{args.profile}` prompt",
            "{n} ANSWER cases, N=5, temperature 0.7, seeds 42-46, one server session, both "
            f"conditions; the linker adds a hint to {hinted} of them (elsewhere the prompts are "
            "identical). Scored against the frozen gold. Linked minus baseline.",
        )
    else:
        text = render(base, linked)
    if args.write:
        args.write.write_text(text)
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
