"""Generation-only bake-off harness (Task 9).

Why not the full pipeline: `OLLAMA_MODEL` drives classify and answer as well as
generate, so a text-to-SQL specialist that over-refuses in classify would never
reach generation and would read as low pass@N, and its answer-writing quality
would leak into a comparison of SQL generation. This harness runs only the
generation stage:

- `ANSWER`-expected cases only (the population pass@1 is scored over);
- no classify, no answer, no verifier, no agreement gate;
- N=5 candidates per case, each its own seeded call (seed = OLLAMA_SEED + i,
  temperature 0.7, exactly as `generate.generate_candidates`), prompted in the
  format given by `--profile` (see evals/gen_prompts.py);
- then the pipeline's own guard -> execute -> vote, unmodified.

Records match `run_eval.py`'s per-case shape closely enough for
`evals.passn_scoring` to score them, so pass@1 (the vote's pick) and pass@N come
from the same code path as every earlier figure. Every candidate keeps its raw
model reply and finish reason, and a failed model call is logged as an error
candidate rather than dropped. pass@1 here is the vote's pick with no agreement
threshold, so it is not comparable to a full-pipeline execution accuracy.

`--smoke K` runs only K cases (the first ANSWER case of each of the first K
tiers), prints what the model said and what became of it, and exits 3 unless all
but at most one of them produced a candidate that parses and executes (zero rows
allowed): a cheap check that the server responds and the model emits runnable SQL
before the full run spends hours.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx

from evals import gen_prompts, heldout_config, measurement_pin, scoring
from evals.gen_prompts import PROFILES, SchemaInfo
from evals.passn_scoring import GOLD_PATH, compute_pass_at_n, load_jsonl
from evals.scoring import case_matches
from ledgerql import consensus as consensus_module
from ledgerql import entity_link, generate, pipeline, schema_index
from ledgerql import execute as execute_module
from ledgerql import guardrails as guardrails_module

DEFAULT_N = 5
DEFAULT_TEMPERATURE = generate.OLLAMA_CONSENSUS_TEMPERATURE
DEFAULT_MAX_TOKENS = 2048  # OmniSQL's card uses 2048 for its reasoning-then-SQL replies
SMOKE_EXIT_CODE = 3


@dataclass(frozen=True)
class Generation:
    text: str
    finish_reason: str | None
    # For a failed call: the server's message (HTTP status errors) or the
    # exception text. Never mixed into `text`, so it cannot be parsed as SQL.
    detail: str | None = None


class HttpGenerator:
    """One vLLM `/v1/chat/completions` call per candidate. The messages are sent
    as given (no system prompt is added), so a profile controls the whole
    prompt; the model's own chat template is applied server-side."""

    def __init__(
        self,
        model: str,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        host: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 900.0,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._http = http or httpx.Client(
            base_url=host or os.environ.get("VLLM_HOST", "http://localhost:8000"), timeout=timeout
        )

    def __call__(self, messages: list[dict], seed: int) -> Generation:
        response = self._http.post(
            "/v1/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "seed": seed,
                "max_tokens": self.max_tokens,
            },
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        return Generation(
            text=choice["message"]["content"], finish_reason=choice.get("finish_reason")
        )


def select_cases(gold: list[dict], only: set[str] | None = None) -> list[dict]:
    return [c for c in gold if c["expected"] == "ANSWER" and (only is None or c["id"] in only)]


def smoke_cases(cases: list[dict], k: int) -> list[dict]:
    """The first case of each of the first k distinct tiers."""
    picked, seen = [], set()
    for case in cases:
        if case["tier"] not in seen:
            seen.add(case["tier"])
            picked.append(case)
        if len(picked) == k:
            break
    return picked


def _executed(record: dict) -> bool:
    """A candidate the model really wrote that parsed, passed the guard and executed. Zero rows is
    allowed: a wrong entity name literal executes and returns nothing, which is exactly the
    failure entity linking targets, so it cannot fail the gate that decides whether to run a
    linked-versus-unlinked comparison. A call error (HTTP status, timeout) is not a candidate."""
    return any(
        c["guard_ok"]
        and c["exec_error"] is None
        and c["n_rows"] is not None
        and not str(c.get("finish_reason")).startswith("error:")
        for c in record["candidates"]
    )


def smoke_ok(records: list[dict]) -> bool:
    """All but at most one smoke case has a candidate that parses and executes (a single-case
    smoke tolerates nothing). The gate answers "does the server respond and do candidates parse
    and run?", not "are they right": correctness is what the full run measures."""
    need = len(records) - 1 if len(records) >= 2 else 1
    return sum(_executed(r) for r in records) >= need


def _safe_generate(generate_fn, messages: list[dict], seed: int) -> Generation:
    try:
        return generate_fn(messages, seed)
    except httpx.HTTPStatusError as e:
        # The status and body are the whole diagnosis (a 400 naming the context
        # length, a 500 from a dead engine), so they are kept.
        return Generation(
            text="",
            finish_reason=f"error:HTTPStatusError:{e.response.status_code}",
            detail=e.response.text[:1000],
        )
    except Exception as e:  # noqa: BLE001 -- a failed call is a logged outcome, not a crash
        return Generation(text="", finish_reason=f"error:{type(e).__name__}", detail=str(e)[:1000])


def run(
    cases: list[dict],
    profile: str,
    generate_fn,
    *,
    db_path: str,
    schema: SchemaInfo,
    schema_context: str,
    n: int = DEFAULT_N,
    concurrency: int = 8,
    log=lambda msg: None,
    entity_linker=None,
) -> list[dict]:
    hints = [
        entity_link.hint_for(c["question"], entity_linker) if entity_linker is not None else ""
        for c in cases
    ]
    prompts = [
        gen_prompts.build_messages(
            profile, c["question"], schema=schema, schema_context=schema_context, entity_hint=h
        )
        for c, h in zip(cases, hints, strict=True)
    ]
    gold = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    records = []
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                [
                    pool.submit(_safe_generate, generate_fn, prompts[ci], generate.OLLAMA_SEED + i)
                    for i in range(n)
                ]
                for ci in range(len(cases))
            ]
            for case, hint, case_futures in zip(cases, hints, futures, strict=True):
                gens = [f.result() for f in case_futures]
                records.append(_score_case(case, gens, gold, db_path))
                records[-1]["entity_hint"] = hint
                log(f"{case['id']}: {_outcome(records[-1])}")
    finally:
        gold.close()
    return records


def _outcome(record: dict) -> str:
    return (
        f"correct={record['execution_correct']} agreement={record['confidence']:.1f} "
        f"reason={record['reason_code']}"
    )


def _score_case(case: dict, gens: list[Generation], gold, db_path: str) -> dict:
    sqls = [gen_prompts.extract_sql(g.text) for g in gens]
    guards = [guardrails_module.validate(sql, db_path=db_path) for sql in sqls]
    execs = [execute_module.execute(g.sql, db_path=db_path) if g.ok else None for g in guards]
    consensus = consensus_module.vote(guards, execs)
    candidates = pipeline._candidate_log(sqls, guards, execs)
    for cand, gen in zip(candidates, gens, strict=True):
        cand["raw"] = gen.text
        cand["finish_reason"] = gen.finish_reason
        cand["error_detail"] = gen.detail

    correct = False
    if consensus.reason_code is None:
        gold_rows = gold.execute(case["gold_sql"]).fetchall()
        correct = case_matches(
            case, gold_rows, consensus.rows, db_path, pred_columns=consensus.columns
        )
    return {
        "id": case["id"],
        "tier": case["tier"],
        "expected": case["expected"],
        "generated_sql": consensus.sql,
        "answer": None,
        "columns": consensus.columns,
        "rows": consensus.rows,
        "reason_code": consensus.reason_code,
        "guardrail_events": consensus.events,
        "confidence": consensus.agreement,
        "candidates": candidates,
        "execution_correct": correct,
    }


def summarize(records: list[dict], cases_by_id: dict, db_path: str) -> dict:
    cands = [c for r in records for c in r["candidates"]]
    exec_errors = Counter(
        c["exec_error"].split(":", 1)[0] for c in cands if c["exec_error"] is not None
    )
    return {
        "passn": compute_pass_at_n(records, cases_by_id, db_path),
        "candidates": {
            "total": len(cands),
            "guard_rejected": sum(not c["guard_ok"] for c in cands),
            "guard_reasons": dict(Counter(c["reason_code"] for c in cands if not c["guard_ok"])),
            "executed": sum(c["guard_ok"] and c["exec_error"] is None for c in cands),
            "exec_errors": dict(exec_errors),
            "empty_result": sum(bool(c["empty"]) for c in cands),
            "no_sql_extracted": sum(c["sql"] == "" for c in cands),
            "truncated": sum(c["finish_reason"] == "length" for c in cands),
            "call_errors": sum(str(c["finish_reason"]).startswith("error:") for c in cands),
        },
    }


def _markdown(stats: dict, profile: str, meta: dict) -> str:
    o = stats["passn"]["overall"]
    c = stats["candidates"]
    lines = [
        f"# Generation-only eval: {meta.get('model', '?')} / profile `{profile}`",
        "",
        f"{o['total']} ANSWER-expected cases, N candidates each; vote pick with no gates.",
        "",
        "| metric | value |",
        "|---|---|",
        f"| pass@1 (vote pick) | {o['pass_1']}/{o['total']} ({o['pass_at_1']:.1%}) |",
        f"| pass@N | {o['pass_n']}/{o['total']} ({o['pass_at_n']:.1%}) |",
        f"| selection headroom | {o['pass_n'] - o['pass_1']} |",
        "",
        "| tier | n | pass@1 | pass@N |",
        "|---|---|---|---|",
    ]
    for tier, b in stats["passn"]["by_tier"].items():
        lines.append(f"| {tier} | {b['total']} | {b['pass_1']} | {b['pass_n']} |")
    lines += [
        "",
        "## Candidate outcomes",
        "",
        f"- candidates: {c['total']}; executed: {c['executed']}; "
        f"guard-rejected: {c['guard_rejected']} {c['guard_reasons']}",
        f"- execution errors by kind (dialect problems show here): {c['exec_errors']}",
        f"- empty results: {c['empty_result']}; no SQL extracted: {c['no_sql_extracted']}; "
        f"truncated at max_tokens: {c['truncated']}; failed model calls: {c['call_errors']}",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(
    records: list[dict], stats: dict, out_dir: Path, *, profile: str, meta: dict, tag: str = ""
) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"gen_only_{profile}{tag}"
    (out_dir / f"{stem}.jsonl").write_text(
        "".join(json.dumps(r, default=str) + "\n" for r in records)
    )
    (out_dir / f"{stem}_summary.json").write_text(
        json.dumps({"meta": meta, **stats}, indent=2, default=str)
    )
    (out_dir / f"{stem}.md").write_text(_markdown(stats, profile, meta))


def _print_smoke(records: list[dict]) -> None:
    for r in records:
        print(f"\n--- smoke {r['id']} ({r['tier']}): {_outcome(r)}")
        for i, c in enumerate(r["candidates"][:2]):
            print(f"  candidate {i}: finish={c['finish_reason']} guard_ok={c['guard_ok']} "
                  f"exec_error={c['exec_error']} n_rows={c['n_rows']}")  # fmt: skip
            if c.get("error_detail"):
                print(f"    error detail: {c['error_detail'][:600]!r}")
            print(f"    raw: {c['raw'][:600]!r}")
            print(f"    sql: {c['sql'][:400]!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--model", default=os.environ.get("OLLAMA_MODEL"))
    ap.add_argument("--host", default=None, help="vLLM base URL (default $VLLM_HOST)")
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--smoke", type=int, default=0, help="run only K cases and gate on them")
    ap.add_argument(
        "--entity-link",
        action="store_true",
        help="add each question's resolved companies (ledgerql.entity_link) to the prompt",
    )
    ap.add_argument("--cases", help="comma-separated case ids to run (default: every ANSWER case)")
    ap.add_argument(
        "--gold",
        type=Path,
        default=GOLD_PATH,
        help="gold file (default: gold.jsonl, v1); a held-out file must match its freeze pin",
    )
    args = ap.parse_args(argv)
    if not args.model:
        ap.error("--model (or $OLLAMA_MODEL) is required")

    scoring.require_frozen(args.gold)
    heldout_config.require_declared(
        args.gold
    )  # ... and unless the code is the declared configuration
    measurement_pin.require_pinned(args.gold)  # ... and the scoring code and environment are pinned
    gold = load_jsonl(args.gold)
    cases = select_cases(gold, set(args.cases.split(",")) if args.cases else None)
    if args.smoke:
        cases = smoke_cases(cases, args.smoke)

    generator = HttpGenerator(args.model, args.temperature, args.max_tokens, args.host)
    records = run(
        cases,
        args.profile,
        generator,
        db_path=args.db,
        schema=gen_prompts.introspect(args.db),
        schema_context=schema_index.get_schema_context(),
        n=args.n,
        concurrency=args.concurrency,
        log=lambda msg: print(msg, file=sys.stderr, flush=True),
        entity_linker=entity_link.EntityLinker.from_db(args.db) if args.entity_link else None,
    )
    if args.smoke:
        _print_smoke(records)
        ok = smoke_ok(records)
        print(f"\nsmoke {'PASSED' if ok else 'FAILED'} ({args.smoke} cases)")
        return 0 if ok else SMOKE_EXIT_CODE

    stats = summarize(records, {c["id"]: c for c in gold}, args.db)
    tag = "_linked" if args.entity_link else ""
    meta = {
        "model": args.model,
        "profile": args.profile,
        "n": args.n,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "entity_link": args.entity_link,
        "gold": args.gold.name,
    }
    write_outputs(records, stats, args.out, profile=args.profile, meta=meta, tag=tag)
    print((args.out / f"gen_only_{args.profile}{tag}.md").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
