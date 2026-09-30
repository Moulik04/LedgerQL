# ruff: noqa: E501  (markdown table headers are single lines)
"""Re-score everything under gold v2, side by side with v1.

Three verdicts are computed for every result, in one pass:

- `v1`: the original gold and comparator (`gold.jsonl`, `run_eval.results_match`).
- `v2`: gold v2, strict comparator (the headline, evals/README.md 6g).
- `v2r`: gold v2, relaxed comparator (extra columns ignored), a labelled second figure.

Two evidence sources, both tracked and both re-executed locally:

- the Phase 5 per-case reports (`reports/eval_bridges2_*.jsonl`): each record's own
  winner rows, scored exactly as `run_eval` scores them;
- the bake-off (`reports/bakeoff_candidates.jsonl`): every candidate's SQL is guarded
  and executed, and the vote's pick is recomputed with the pipeline's own rule
  (biggest cluster of identical result sets, ties to the earliest candidate).

    python -m evals.rescore_v2 phase5        # Phase 5 measured runs, v1 | v2 | v2r
    python -m evals.rescore_v2 bakeoff       # pass@1 / pass@N per model and prompt
    python -m evals.rescore_v2 agreement     # cross-model agreement and the policy table
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from evals import bakeoff_evidence
from evals.passn_scoring import _run_candidate, load_jsonl
from evals.scoring import case_match, load_gold
from ledgerql.consensus import _row_sort_key

DEFAULT_DB = "data/ledgerql.duckdb"
VERSIONS = ("v1", "v2", "v2r")
LABELS = {"v1": "v1", "v2": "v2 strict", "v2r": "v2 relaxed"}
SCORED = ("ANSWER", "ANSWER_WITH_ASSUMPTION")


def _connect(db: str):
    return duckdb.connect(db, read_only=True, config={"enable_external_access": "false"})


class Gold:
    """Both editions' cases and their gold rows, executed once."""

    def __init__(self, db: str = DEFAULT_DB):
        self.db = db
        self.v1, self.v2 = load_gold("v1"), load_gold("v2")
        con = _connect(db)
        try:
            self.rows = {
                "v1": {
                    i: con.execute(c["gold_sql"]).fetchall()
                    for i, c in self.v1.items()
                    if c.get("gold_sql")
                },
                "v2": {
                    i: con.execute(c["gold_sql"]).fetchall()
                    for i, c in self.v2.items()
                    if c.get("gold_sql")
                },
            }
        finally:
            con.close()

    def verdicts(self, case_id: str, pred_rows: list | None) -> dict[str, bool]:
        """{'v1': bool, 'v2': bool, 'v2r': bool} for one result (None = no result)."""
        if pred_rows is None or case_id not in self.rows["v1"]:
            return dict.fromkeys(VERSIONS, False)
        rows = [tuple(r) for r in pred_rows]
        return {
            "v1": case_match(self.v1[case_id], self.rows["v1"][case_id], rows, self.db).matched,
            "v2": case_match(self.v2[case_id], self.rows["v2"][case_id], rows, self.db).matched,
            "v2r": case_match(
                self.v2[case_id], self.rows["v2"][case_id], rows, self.db, mode="relaxed"
            ).matched,
        }

    def via(self, case_id: str, pred_rows: list) -> frozenset:
        rows = [tuple(r) for r in pred_rows]
        return case_match(self.v2[case_id], self.rows["v2"][case_id], rows, self.db).via


# --------------------------------------------------------------------------
# Phase 5 per-case reports
# --------------------------------------------------------------------------


@dataclass
class RecordScore:
    id: str
    tier: str
    expected: str
    answered: bool
    recorded: bool  # the report's own execution_correct
    verdict: dict[str, bool]


def score_report(records: list[dict], gold: Gold) -> list[RecordScore]:
    """Each scored record, judged by the winner rows it recorded, exactly as `run_eval`
    judged them: no execution error, and the rows match."""
    out = []
    for rec in records:
        if rec["expected"] not in SCORED or not gold.v1[rec["id"]].get("gold_sql"):
            continue
        rows = rec.get("rows") if rec.get("execution_error") is None else None
        out.append(
            RecordScore(
                id=rec["id"],
                tier=rec["tier"],
                expected=rec["expected"],
                answered=rec.get("answer") is not None,
                recorded=rec.get("execution_correct") is True,
                verdict=gold.verdicts(rec["id"], rows),
            )
        )
    return out


def accuracy(scores: list[RecordScore], expected: str = "ANSWER") -> dict[str, int]:
    """{version: number correct} over the cases with this expected behaviour."""
    pool = [s for s in scores if s.expected == expected]
    # ANSWER cases count the winner's result whether or not the answer was later withheld,
    # as `run_eval`'s execution accuracy does. Assumption cases count only answers actually
    # given: an abstain that happened to leave matching rows is not "answered correctly".
    given_only = expected == "ANSWER_WITH_ASSUMPTION"
    return {
        v: sum(s.verdict[v] and (s.answered or not given_only) for s in pool) for v in VERSIONS
    } | {"n": len(pool)}


def verdict_changes(scores: list[RecordScore]) -> list[RecordScore]:
    """Cases where the strict v2 verdict differs from v1's, in either direction."""
    return [s for s in scores if s.verdict["v1"] != s.verdict["v2"]]


def tier_accuracy(scores: list[RecordScore]) -> dict[str, dict[str, int]]:
    tiers: dict[str, dict[str, int]] = defaultdict(lambda: Counter())
    for s in scores:
        if s.expected != "ANSWER":
            continue
        tiers[s.tier]["n"] += 1
        for v in VERSIONS:
            tiers[s.tier][v] += s.verdict[v]
    return {t: dict(c) for t, c in sorted(tiers.items())}


# --------------------------------------------------------------------------
# The bake-off: every candidate executed, the vote recomputed
# --------------------------------------------------------------------------


@dataclass
class Cand:
    sql: str
    rows: list | None  # None: guard-rejected or failed to execute
    verdict: dict[str, bool]
    via: frozenset = frozenset()
    guard_sql: str | None = None  # the SQL actually executed (after the guard's rewrite)

    @property
    def key(self) -> tuple | None:
        """The consensus cluster key: the result's rows, order-insensitive."""
        return None if self.rows is None else tuple(sorted(self.rows, key=_row_sort_key))


@dataclass
class Pool:
    model: str
    profile: str
    id: str
    tier: str
    cands: list[Cand] = field(default_factory=list)
    winner: int | None = None  # index of the vote's pick, None if nothing executed
    recorded_winner_sql: str | None = None

    def pass_at_1(self, v: str) -> bool:
        return self.winner is not None and self.cands[self.winner].verdict[v]

    def pass_at_n(self, v: str) -> bool:
        return any(c.verdict[v] for c in self.cands)


def vote_winner(keys: list[tuple | None]) -> int | None:
    """`consensus.vote`: the first index of the largest cluster of identical results."""
    clusters: dict[tuple, list[int]] = {}
    for i, key in enumerate(keys):
        if key is not None:
            clusters.setdefault(key, []).append(i)
    if not clusters:
        return None
    return max(clusters.values(), key=len)[0]


def score_bakeoff(evidence: list[dict], gold: Gold) -> list[Pool]:
    pools = []
    for rec in evidence:
        case = gold.v1[rec["id"]]
        if case["expected"] != "ANSWER":
            continue
        pool = Pool(rec["model"], rec["profile"], rec["id"], case["tier"])
        pool.recorded_winner_sql = rec.get("winner_sql")
        for sql in rec["sqls"]:
            guard_sql, rows = _run_candidate(sql, gold.db)
            verdict = gold.verdicts(rec["id"], rows)
            via = gold.via(rec["id"], rows) if rows and verdict["v2"] else frozenset()
            pool.cands.append(Cand(sql, rows, verdict, via, guard_sql))
        pool.winner = vote_winner([c.key for c in pool.cands])
        pools.append(pool)
    return pools


def passn_table(pools: list[Pool]) -> dict[tuple[str, str], dict[str, tuple[int, int]]]:
    """{(model, profile): {version: (pass@1, pass@N)}} over the ANSWER cases."""
    out: dict = defaultdict(lambda: {v: [0, 0] for v in VERSIONS})
    for p in pools:
        for v in VERSIONS:
            out[(p.model, p.profile)][v][0] += p.pass_at_1(v)
            out[(p.model, p.profile)][v][1] += p.pass_at_n(v)
    return {k: {v: tuple(c) for v, c in d.items()} for k, d in out.items()}


def union_solved(pools: list[Pool], v: str) -> set[str]:
    return {p.id for p in pools if p.pass_at_n(v)}


def verdict_changes_by_case(pools: list[Pool]) -> dict[str, dict[str, int]]:
    """Per case, candidates matching under each version, for cases whose count differs
    between v1 and v2 strict."""
    per: dict[str, Counter] = defaultdict(Counter)
    for p in pools:
        for c in p.cands:
            for v in VERSIONS:
                per[p.id][v] += c.verdict[v]
    return {i: dict(c) for i, c in sorted(per.items()) if c["v1"] != c["v2"]}


def identifier_counts(pools: list[Pool]) -> Counter:
    """How many strict-v2 matching candidates matched through each identifier type."""
    counts: Counter = Counter()
    for p in pools:
        for c in p.cands:
            for t in c.via:
                counts[t] += 1
    return counts


def load_evidence(path: Path | None = None) -> list[dict]:
    return bakeoff_evidence.load(path) if path else bakeoff_evidence.load()


def load_report(path: Path) -> list[dict]:
    return load_jsonl(path)


# --------------------------------------------------------------------------
# Assumption cases: answered correctly / abstained / answered wrong
# --------------------------------------------------------------------------


def assumption_split(scores: list[RecordScore]) -> dict[str, dict[str, int]]:
    """{version: {answered_correct, abstained, answered_wrong}} over the
    `ANSWER_WITH_ASSUMPTION` cases. Whether the answer *states* its assumption is
    `answer_must_state`, which nothing scores yet, so `answered_correct` is an upper
    bound on "answered with the assumption stated"."""
    pool = [s for s in scores if s.expected == "ANSWER_WITH_ASSUMPTION"]
    out = {}
    for v in VERSIONS:
        abstained = sum(not s.answered for s in pool)
        correct = sum(s.answered and s.verdict[v] for s in pool)
        out[v] = {
            "n": len(pool),
            "answered_correct": correct,
            "abstained": abstained,
            "answered_wrong": len(pool) - abstained - correct,
        }
    return out


# --------------------------------------------------------------------------
# Agreement
# --------------------------------------------------------------------------


def pool_rows(pools: list[Pool], model: str, profile: str, v: str) -> list[dict]:
    """The `signal_precheck` row shape for one bake-off run under one gold version."""
    out = []
    for p in pools:
        if (p.model, p.profile) != (model, profile):
            continue
        answered = p.winner is not None
        out.append(
            {
                "id": p.id,
                "answered": answered,
                "winner_correct": p.pass_at_1(v),
                "winner_rows": p.cands[p.winner].rows if answered else None,
            }
        )
    return out


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

PHASE5_REPORTS = (
    ("Qwen3-30B (measured)", "eval_bridges2_qwen3_30b_measured.jsonl"),
    ("Qwen2.5-32B AWQ (measured)", "eval_bridges2_qwen25_32b_measured.jsonl"),
    ("Qwen3-30B (first run)", "eval_bridges2_qwen3_30b.jsonl"),
    ("Qwen2.5-32B AWQ (first run)", "eval_bridges2_qwen25_32b.jsonl"),
)
MODEL_NAMES = {
    "qwen3_30b": "Qwen3-30B",
    "qwen25_32b_awq": "Qwen2.5-32B AWQ",
    "xiyan_32b": "XiYanSQL-32B",
}


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def _configs(records: list[dict]) -> dict[str, list[dict]]:
    """The three configurations every published Phase 5 figure is one of: as recorded (repair
    on), the shipped config (`exec_error` repair off), and shipped plus the year verifier
    (the current headline)."""
    from evals.replay_repair_off import revert_exec_error_repairs
    from evals.replay_year_rule import apply_year_rule

    shipped = revert_exec_error_repairs(records)
    return {
        "as recorded (repair on)": records,
        "shipped (repair off)": shipped,
        "shipped + year rule": apply_year_rule(shipped),
    }


def render_phase5(gold: Gold, reports_dir: Path) -> str:
    lines = [
        "## Phase 5 per-case reports: v1 | v2 strict | v2 relaxed",
        "",
        "Each record's own winner rows, scored as `run_eval` scores them, in the three "
        "configurations the published figures come from. `shipped (repair off)` is the config "
        "DECISIONS.md's assumption table used; `+ year rule` is the current headline "
        "(`evals/replay_year_rule.py`).",
        "",
        "| run | config | ANSWER (50) v1 | v2 | v2 relaxed | assumption cases answered correctly (19) v1 | v2 | v2 relaxed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    runs = []
    for label, name in PHASE5_REPORTS[:2]:
        for config, records in _configs(load_report(reports_dir / name)).items():
            scores = score_report(records, gold)
            a, w = accuracy(scores, "ANSWER"), accuracy(scores, "ANSWER_WITH_ASSUMPTION")
            lines.append(
                f"| {label} | {config} | {_pct(a['v1'], 50)} | {_pct(a['v2'], 50)} "
                f"| {_pct(a['v2r'], 50)} | {w['v1']}/19 | {w['v2']}/19 | {w['v2r']}/19 |"
            )
            runs.append((label, config, scores))
    lines += ["", "### Assumption cases (19): answered correctly / abstained / answered wrong", ""]
    lines += [
        "`answered correctly` is an upper bound on *answered with the assumption stated*: "
        "`answer_must_state` is still unscored. An abstain is reported on its own, never as "
        "handled.",
        "",
        "| run | config | version | answered correctly | abstained | answered wrong |",
        "|---|---|---|---|---|---|",
    ]
    for label, config, scores in runs:
        if config == "as recorded (repair on)":
            continue
        split = assumption_split(scores)
        for v in VERSIONS:
            s = split[v]
            lines.append(
                f"| {label} | {config} | {LABELS[v]} | {s['answered_correct']} | "
                f"{s['abstained']} | {s['answered_wrong']} |"
            )
    lines += ["", "### Per tier (ANSWER cases), measured runs, shipped (repair off)", ""]
    for label, config, scores in runs:
        if config != "shipped (repair off)":
            continue
        lines += [
            f"**{label}**",
            "",
            "| tier | n | v1 | v2 | v2 relaxed |",
            "|---|---|---|---|---|",
        ]
        for tier, c in tier_accuracy(scores).items():
            lines.append(f"| {tier} | {c['n']} | {c['v1']} | {c['v2']} | {c['v2r']} |")
        lines.append("")
    lines += ["### Every case whose verdict changes (v1 -> v2 strict), in either direction", ""]
    for label, config, scores in runs:
        changed = verdict_changes(scores)
        gained = [s.id for s in changed if s.verdict["v2"]]
        lost = [s.id for s in changed if not s.verdict["v2"]]
        lines.append(f"- **{label}, {config}**: gained {gained}; lost {lost}")
    first = []
    for label, name in PHASE5_REPORTS[2:]:
        scores = score_report(load_report(reports_dir / name), gold)
        a = accuracy(scores, "ANSWER")
        mism = [s.id for s in scores if s.verdict["v1"] != s.recorded]
        first.append(
            f"{label}: ANSWER v1 {a['v1']}, v2 {a['v2']}, v2 relaxed {a['v2r']} of 50 "
            f"(recorded != v1 recomputed: {mism})"
        )
    lines += [
        "",
        "The two `first run` files predate later comparator fixes, so some of their "
        "recorded verdicts differ from v1 recomputed; the measured files are the reference.",
        "",
    ]
    lines += [f"- {x}" for x in first]
    return "\n".join(lines) + "\n"


def render_bakeoff(pools: list[Pool]) -> str:
    table = passn_table(pools)
    lines = [
        "## Bake-off: pass@1 -> pass@N over the 50 ANSWER cases, N=5",
        "",
        "Each cell: v1 | v2 strict | v2 relaxed. pass@1 is the vote pick with no gates.",
        "",
        "| model | prompt | v1 | v2 strict | v2 relaxed |",
        "|---|---|---|---|---|",
    ]
    for (model, profile), d in sorted(table.items()):
        cells = " | ".join(f"{d[v][0]} -> {d[v][1]}" for v in VERSIONS)
        lines.append(f"| {MODEL_NAMES[model]} | {profile} | {cells} |")
    ranges = {v: [x for d in table.values() for x in (d[v][1],)] for v in VERSIONS}
    lines += ["", "pass@N range over the nine cells: " + "; ".join(
        f"{LABELS[v]} {min(r)}-{max(r)} of 50" for v, r in ranges.items())]  # fmt: skip
    lines += ["", "### Union over all nine runs (2250 candidates)", ""]
    for v in VERSIONS:
        solved = union_solved(pools, v)
        never = sorted({p.id for p in pools} - solved)
        lines.append(f"- {LABELS[v]}: {len(solved)}/50 solved by some candidate; never: {never}")
    lines += ["", "Per model, union over its three prompts:", ""]
    lines += ["| model | v1 | v2 strict | v2 relaxed |", "|---|---|---|---|"]
    for model in MODEL_NAMES:
        mine = [p for p in pools if p.model == model]
        lines.append(
            f"| {MODEL_NAMES[model]} | "
            + " | ".join(str(len(union_solved(mine, v))) for v in VERSIONS)
            + " |"
        )
    lines += [
        "",
        "### Candidates whose verdict changes, per case (of 45; v1 | v2 strict | v2 relaxed)",
        "",
    ]
    flips: dict[str, Counter] = defaultdict(Counter)
    for p in pools:
        for c in p.cands:
            if c.verdict["v1"] and not c.verdict["v2"]:
                flips[p.id]["lost"] += 1
            if c.verdict["v2"] and not c.verdict["v1"]:
                flips[p.id]["gained"] += 1
    counts = verdict_changes_by_case(pools)
    lines += ["| case | v1 | v2 | v2 relaxed | gained | lost |", "|---|---|---|---|---|---|"]
    for i in sorted(set(counts) | set(flips)):
        c = counts.get(i) or {
            v: sum(cd.verdict[v] for p in pools if p.id == i for cd in p.cands) for v in VERSIONS
        }
        lines.append(
            f"| {i} | {c['v1']} | {c['v2']} | {c['v2r']} | {flips[i]['gained']} | {flips[i]['lost']} |"
        )
    ids = identifier_counts(pools)
    lines += [
        "",
        f"Strict-v2 matches by identifier type on entity columns (V2): {dict(ids)}.",
    ]
    return "\n".join(lines) + "\n"


def _auroc_line(a_rows: list[dict], b_rows: list[dict]) -> str:
    from evals.pairwise_agreement import pair_stats

    s = pair_stats(a_rows, b_rows)
    if s["auroc"] is None:
        area = "n/a"
    else:
        area = f"{s['auroc']:.3f} [{s['ci'][0]:.3f}, {s['ci'][1]:.3f}]"
    pol = s["policy"]
    return (
        f"{area} | {s['wrong']}/{s['answered']} -> {pol['wrong']}/{pol['answered']} "
        f"| {s['correct']} -> {pol['correct']}"
    )


def render_agreement(pools: list[Pool], gold: Gold, reports_dir: Path, db: str) -> str:
    from itertools import permutations

    from evals import signal_precheck as sp

    lines = [
        "## Cross-model agreement and the policy table",
        "",
        "Agreement is still raw result equivalence between the two winners (order-insensitive, "
        "floats to 1e-6); only the *correctness labels* it is scored against change with the "
        "gold version. A winner that returns extra columns is `differ` from one that does not, "
        "even where both are right under v2.",
        "",
        "### Bake-off, `current` prompt, generation only (AUROC of predicting A's correctness)",
        "",
        "| pair A -> B | version | AUROC [95% CI] | A wrong -> wrong under 'both agree' | A correct -> correct |",
        "|---|---|---|---|---|",
    ]
    models = list(MODEL_NAMES)
    for a, b in permutations(models, 2):
        for v in VERSIONS:
            ra, rb = pool_rows(pools, a, "current", v), pool_rows(pools, b, "current", v)
            lines.append(
                f"| {MODEL_NAMES[a]} -> {MODEL_NAMES[b]} | {LABELS[v]} | {_auroc_line(ra, rb)} |"
            )
    lines += [
        "",
        "### Pipeline runs (Qwen3-30B and Qwen2.5-32B, measured, repair off)",
        "",
        "| model | gold | answered | wrong (confidently wrong) | policy: answers | policy: wrong | policy: correct |",
        "|---|---|---|---|---|---|---|",
    ]
    for year_rule in (False, True):
        for gv in ("v1", "v2"):
            cases = load_gold(gv)
            rows = {
                m: sp.build_rows(
                    load_report(reports_dir / f"eval_bridges2_{m}_measured.jsonl"),
                    cases,
                    db,
                    year_rule=year_rule,
                )
                for m in ("qwen3_30b", "qwen25_32b")
            }
            for own, other in (("qwen3_30b", "qwen25_32b"), ("qwen25_32b", "qwen3_30b")):
                out = sp.policy_breakdown(rows[own], rows[other])
                pol = out["policy"]
                tag = f"{gv}{' + year rule' if year_rule else ''}"
                lines.append(
                    f"| {own} | {tag} | {out['answered']} | {out['wrong']} "
                    f"({out['wrong'] / out['answered']:.1%}) | {pol['answered']} | "
                    f"{pol['wrong']} ({pol['wrong'] / pol['answered']:.1%}) | {pol['correct']} |"
                )
    return "\n".join(lines) + "\n"


def build_report(db: str = DEFAULT_DB, reports_dir: Path = Path("reports")) -> str:
    gold = Gold(db)
    pools = score_bakeoff(load_evidence(), gold)
    parts = [
        "# Gold v2 re-score",
        "",
        "Generated by `python -m evals.rescore_v2 report`. Rules: `evals/README.md` 6g. "
        "v1 = `gold.jsonl` and the original comparator; v2 strict = `gold_v2.jsonl` (the "
        "headline); v2 relaxed = the same gold with extra candidate columns ignored.",
        "",
        render_phase5(gold, reports_dir),
        render_bakeoff(pools),
        render_agreement(pools, gold, reports_dir, db),
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("part", choices=("phase5", "bakeoff", "agreement", "report"))
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--write", type=Path, help="write the report here (part=report)")
    args = ap.parse_args(argv)
    if args.part == "report":
        text = build_report(args.db, args.reports_dir)
        if args.write:
            args.write.write_text(text)
            print(f"wrote {args.write}")
        else:
            print(text)
        return 0
    gold = Gold(args.db)
    if args.part == "phase5":
        print(render_phase5(gold, args.reports_dir))
        return 0
    pools = score_bakeoff(load_evidence(), gold)
    print(
        render_bakeoff(pools)
        if args.part == "bakeoff"
        else render_agreement(pools, gold, args.reports_dir, args.db)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
