# ruff: noqa: E501  (markdown table headers are single lines)
"""Re-score everything under gold v3, side by side with v1 and v2.

Four verdicts are computed for every result, in one pass:

- `v1`: the original gold and comparator (`gold.jsonl`, `run_eval.results_match`).
- `v2`: gold v2, strict comparator (evals/README.md 6g).
- `v3`: gold v3, strict comparator (the headline, 6i).
- `v3r`: gold v3, relaxed comparator (extra columns ignored), a labelled second figure.

Two evidence sources, both tracked and both re-executed locally:

- the Phase 5 per-case reports (`reports/eval_bridges2_*.jsonl`): each record's own
  winner rows, scored exactly as `run_eval` scores them;
- the bake-off (`reports/bakeoff_candidates.jsonl`): every candidate's SQL is guarded
  and executed, and the vote's pick is recomputed with the pipeline's own rule
  (biggest cluster of identical result sets, ties to the earliest candidate).

    python -m evals.rescore_v2 phase5        # Phase 5 measured runs, v1 | v2 | v3 | v3 relaxed
    python -m evals.rescore_v2 bakeoff       # pass@1 / pass@N per model and prompt
    python -m evals.rescore_v2 agreement     # cross-model agreement and the policy table
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from evals import bakeoff_evidence, must_state, offline_exec
from evals.passn_scoring import load_jsonl
from evals.scoring import case_match, load_gold
from ledgerql import refusal as refusal_module
from ledgerql.consensus import _row_sort_key

DEFAULT_DB = "data/ledgerql.duckdb"
VERSIONS = ("v1", "v2", "v3", "v3r")
LABELS = {"v1": "v1", "v2": "v2 strict", "v3": "v3 strict", "v3r": "v3 relaxed"}
SCORED = ("ANSWER", "ANSWER_WITH_ASSUMPTION")


def _connect(db: str):
    return duckdb.connect(db, read_only=True, config={"enable_external_access": "false"})


class Gold:
    """All three editions' cases and their gold rows, executed once."""

    def __init__(self, db: str = DEFAULT_DB):
        self.db = db
        self.v1, self.v2, self.v3 = load_gold("v1"), load_gold("v2"), load_gold("v3")
        con = _connect(db)
        try:
            self.rows = {
                ed: {
                    i: con.execute(c["gold_sql"]).fetchall()
                    for i, c in cases.items()
                    if c.get("gold_sql")
                }
                for ed, cases in (("v1", self.v1), ("v2", self.v2), ("v3", self.v3))
            }
        finally:
            con.close()

    def verdicts(
        self, case_id: str, pred_rows: list | None, pred_columns: list[str] | None = None
    ) -> dict[str, bool]:
        """{'v1', 'v2', 'v3', 'v3r': bool} for one result (None = no result)."""
        if pred_rows is None or case_id not in self.rows["v1"]:
            return dict.fromkeys(VERSIONS, False)
        rows = [tuple(r) for r in pred_rows]

        def ok(edition, mode="strict"):
            case = getattr(self, edition)[case_id]
            return case_match(
                case, self.rows[edition][case_id], rows, self.db, mode, pred_columns
            ).matched

        return {"v1": ok("v1"), "v2": ok("v2"), "v3": ok("v3"), "v3r": ok("v3", "relaxed")}

    def via(
        self, case_id: str, pred_rows: list, pred_columns: list[str] | None = None
    ) -> frozenset:
        rows = [tuple(r) for r in pred_rows]
        return case_match(
            self.v3[case_id], self.rows["v3"][case_id], rows, self.db, "strict", pred_columns
        ).via


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
    rubric_pass: bool | None = None  # answer_must_state: stated / not stated / not assessed


def score_report(
    records: list[dict], gold: Gold, judge=None, replay_refusal: bool = True
) -> list[RecordScore]:
    """Each scored record, judged by the winner rows it recorded, exactly as `run_eval`
    judged them: no execution error, and the rows match. `rubric_pass` is the
    `answer_must_state` grade of the answer text (patterns; `judge` decides only the
    judge-primary items, None leaves those not assessed)."""
    items = must_state.load_patterns()
    out = []
    for rec in records:
        if rec["expected"] not in SCORED or not gold.v1[rec["id"]].get("gold_sql"):
            continue
        rows = rec.get("rows") if rec.get("execution_error") is None else None
        columns = rec.get("columns")
        rubric_pass = None
        if rec["id"] in items:
            question = gold.v1[rec["id"]]["question"]
            if (
                replay_refusal
                and rec.get("answer") is None
                and rec.get("reason_code")
                and not rec.get("refusal")
            ):
                # a record from before abstains carried an explanation: replay it (it is a pure
                # function of the reason code, the question and the database)
                rec = {**rec, "refusal": refusal_module.explain(
                    rec["reason_code"], question, db_path=gold.db
                ).text}  # fmt: skip
            rubric_pass = must_state.stated(
                must_state.grade_case(
                    items[rec["id"]], rec.get("answer"), rec.get("refusal"), judge, question
                )
            )
        out.append(
            RecordScore(
                id=rec["id"],
                tier=rec["tier"],
                expected=rec["expected"],
                answered=rec.get("answer") is not None,
                recorded=rec.get("execution_correct") is True,
                verdict=gold.verdicts(rec["id"], rows, columns),
                rubric_pass=rubric_pass,
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


def verdict_changes(scores: list[RecordScore], a: str = "v1", b: str = "v3") -> list[RecordScore]:
    """Cases where the strict verdict under edition `b` differs from `a`'s, either direction."""
    return [s for s in scores if s.verdict[a] != s.verdict[b]]


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
    columns: list[str] | None = None
    status: str = "ok"  # offline_exec: ok, guard_rejected, error, timeout or unstable
    attempts: int = 1

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


def score_bakeoff(evidence: list[dict], gold: Gold, strict: bool = True) -> list[Pool]:
    """Score every recorded candidate. A candidate that times out or fails unstably under
    `offline_exec` is recorded with that status, never as "wrong"; with `strict` (the default,
    and what every decision run uses) any such candidate raises `ScoringIncomplete`."""
    pools = []
    unresolved: dict[str, offline_exec.Outcome] = {}
    for rec in evidence:
        case = gold.v1[rec["id"]]
        if case["expected"] != "ANSWER":
            continue
        pool = Pool(rec["model"], rec["profile"], rec["id"], case["tier"])
        pool.recorded_winner_sql = rec.get("winner_sql")
        for i, sql in enumerate(rec["sqls"]):
            out = offline_exec.run_candidate(sql, gold.db)
            if out.status in offline_exec.UNRESOLVED:
                unresolved[f"{rec['model']}/{rec['profile']}/{rec['id']}#{i}"] = out
            rows, columns = out.rows, out.columns
            verdict = gold.verdicts(rec["id"], rows, columns)
            via = gold.via(rec["id"], rows, columns) if rows and verdict["v3"] else frozenset()
            pool.cands.append(
                Cand(sql, rows, verdict, via, out.guard_sql, columns, out.status, out.attempts)
            )
        pool.winner = vote_winner([c.key for c in pool.cands])
        pools.append(pool)
    if strict:
        offline_exec.require_resolved(unresolved)
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
    between any two editions' strict comparators."""
    per: dict[str, Counter] = defaultdict(Counter)
    for p in pools:
        for c in p.cands:
            for v in VERSIONS:
                per[p.id][v] += c.verdict[v]
    return {i: dict(c) for i, c in sorted(per.items()) if len({c["v1"], c["v2"], c["v3"]}) > 1}


def identifier_counts(pools: list[Pool]) -> Counter:
    """How many strict-v3 matching candidates matched through each identifier type."""
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
    """{version: outcome counts} over the `ANSWER_WITH_ASSUMPTION` cases. `answered_correct` is
    split again by the `answer_must_state` grade of its prose: `stated` (the headline),
    `not_stated`, or `unassessed` (nothing to grade, or a judge-decided item without a judge).
    Execution outranks prose: a wrong value is never counted as stated."""
    pool = [s for s in scores if s.expected == "ANSWER_WITH_ASSUMPTION"]
    out = {}
    for v in VERSIONS:
        abstained = sum(not s.answered for s in pool)
        correct_rows = [s for s in pool if s.answered and s.verdict[v]]
        out[v] = {
            "n": len(pool),
            "answered_correct": len(correct_rows),
            "stated": sum(s.rubric_pass is True for s in correct_rows),
            "not_stated": sum(s.rubric_pass is False for s in correct_rows),
            "unassessed": sum(s.rubric_pass is None for s in correct_rows),
            "abstained": abstained,
            "abstained_reason_stated": sum(not s.answered and s.rubric_pass is True for s in pool),
            "answered_wrong": len(pool) - abstained - len(correct_rows),
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


def _cols(prefix: str = "") -> str:
    return " | ".join(f"{prefix}{LABELS[v]}" for v in VERSIONS)


def _sep(n: int) -> str:
    return "|" + "---|" * n


def render_phase5(gold: Gold, reports_dir: Path, judge=None) -> str:
    lines = [
        "## Phase 5 per-case reports: v1 | v2 strict | v3 strict | v3 relaxed",
        "",
        "Each record's own winner rows, scored as `run_eval` scores them, in the three "
        "configurations the published figures come from. `shipped (repair off)` is the config "
        "DECISIONS.md's assumption table used; `+ year rule` is the current headline "
        "(`evals/replay_year_rule.py`).",
        "",
        f"| run | config | {_cols('ANSWER (50): ')} | {_cols('assumption answered correctly (19): ')} |",
        _sep(2 + 2 * len(VERSIONS)),
    ]
    runs = []
    for label, name in PHASE5_REPORTS[:2]:
        for config, records in _configs(load_report(reports_dir / name)).items():
            scores = score_report(records, gold, judge)
            a, w = accuracy(scores, "ANSWER"), accuracy(scores, "ANSWER_WITH_ASSUMPTION")
            cells = " | ".join(_pct(a[v], 50) for v in VERSIONS)
            wcells = " | ".join(f"{w[v]}/19" for v in VERSIONS)
            lines.append(f"| {label} | {config} | {cells} | {wcells} |")
            runs.append((label, config, scores))
    lines += ["", "### Assumption cases (19): answered correctly / abstained / answered wrong", ""]
    lines += [
        "`answered correctly` is split by whether the prose states the assumption "
        "(`answer_must_state`, `evals/must_state.py`; patterns decide most items, a local judge "
        "decides the five judge-primary ones, and without a judge those are *not assessed*; J02 and G04 have no rubric items at all): "
        "**the headline is `stated`**. An abstain is reported on its "
        "own, never as handled.",
        "",
        "| run | config | version | answered correctly | of which **stated** | not stated | no rubric / not gradable | abstained | of which reason stated | answered wrong |",
        _sep(10),
    ]
    for label, config, scores in runs:
        if config == "as recorded (repair on)":
            continue
        split = assumption_split(scores)
        for v in VERSIONS:
            sp = split[v]
            lines.append(
                f"| {label} | {config} | {LABELS[v]} | {sp['answered_correct']} | "
                f"**{sp['stated']}** | {sp['not_stated']} | {sp['unassessed']} | "
                f"{sp['abstained']} | {sp['abstained_reason_stated']} | {sp['answered_wrong']} |"
            )
    lines += ["", "### Per tier (ANSWER cases), measured runs, shipped (repair off)", ""]
    for label, config, scores in runs:
        if config != "shipped (repair off)":
            continue
        lines += [f"**{label}**", "", f"| tier | n | {_cols()} |", _sep(2 + len(VERSIONS))]
        for tier, c in tier_accuracy(scores).items():
            lines.append(f"| {tier} | {c['n']} | " + " | ".join(str(c[v]) for v in VERSIONS) + " |")
        lines.append("")
    lines += ["### Every case whose strict verdict changes, in either direction", ""]
    for label, config, scores in runs:
        for a_, b_ in (("v1", "v3"), ("v2", "v3")):
            changed = verdict_changes(scores, a_, b_)
            gained = [s.id for s in changed if s.verdict[b_]]
            lost = [s.id for s in changed if not s.verdict[b_]]
            lines.append(f"- **{label}, {config}, {a_} -> {b_}**: gained {gained}; lost {lost}")
    first = []
    for label, name in PHASE5_REPORTS[2:]:
        scores = score_report(load_report(reports_dir / name), gold)
        a = accuracy(scores, "ANSWER")
        mism = [s.id for s in scores if s.verdict["v1"] != s.recorded]
        first.append(
            f"{label}: ANSWER "
            + ", ".join(f"{LABELS[v]} {a[v]}" for v in VERSIONS)
            + f" of 50 (recorded != v1 recomputed: {mism})"
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
        f"Each cell: {' | '.join(LABELS[v] for v in VERSIONS)}. pass@1 is the vote pick with no gates.",
        "",
        f"| model | prompt | {_cols()} |",
        _sep(2 + len(VERSIONS)),
    ]
    for (model, profile), d in sorted(table.items()):
        cells = " | ".join(f"{d[v][0]} -> {d[v][1]}" for v in VERSIONS)
        lines.append(f"| {MODEL_NAMES[model]} | {profile} | {cells} |")
    for which, name in ((1, "pass@N"), (0, "pass@1")):
        ranges = {v: [d[v][which] for d in table.values()] for v in VERSIONS}
        lines += [
            "",
            f"{name} range over the nine cells: "
            + "; ".join(f"{LABELS[v]} {min(r)}-{max(r)} of 50" for v, r in ranges.items()),
        ]
    lines += ["", "### Union over all nine runs (2250 candidates)", ""]
    for v in VERSIONS:
        solved = union_solved(pools, v)
        never = sorted({p.id for p in pools} - solved)
        lines.append(f"- {LABELS[v]}: {len(solved)}/50 solved by some candidate; never: {never}")
    lines += ["", "Per model, union over its three prompts:", ""]
    lines += [f"| model | {_cols()} |", _sep(1 + len(VERSIONS))]
    for model in MODEL_NAMES:
        mine = [p for p in pools if p.model == model]
        lines.append(
            f"| {MODEL_NAMES[model]} | "
            + " | ".join(str(len(union_solved(mine, v))) for v in VERSIONS)
            + " |"
        )
    lines += ["", "### Candidates whose verdict changes, per case (of 45)", ""]
    flips: dict[str, Counter] = defaultdict(Counter)
    for p in pools:
        for c in p.cands:
            for a_, b_ in (("v1", "v3"), ("v2", "v3")):
                if c.verdict[a_] and not c.verdict[b_]:
                    flips[p.id][f"lost {a_}->{b_}"] += 1
                if c.verdict[b_] and not c.verdict[a_]:
                    flips[p.id][f"gained {a_}->{b_}"] += 1
    totals = {
        i: {v: sum(cd.verdict[v] for p in pools if p.id == i for cd in p.cands) for v in VERSIONS}
        for i in {p.id for p in pools}
    }
    changed_ids = sorted(
        i for i, t in totals.items() if len({t["v1"], t["v2"], t["v3"]}) > 1 or flips[i]
    )
    lines += [
        f"| case | {_cols()} | gained v1->v3 | lost v1->v3 | gained v2->v3 | lost v2->v3 |",
        _sep(1 + len(VERSIONS) + 4),
    ]
    for i in changed_ids:
        t, f = totals[i], flips[i]
        lines.append(
            f"| {i} | "
            + " | ".join(str(t[v]) for v in VERSIONS)
            + f" | {f['gained v1->v3']} | {f['lost v1->v3']} | {f['gained v2->v3']} | {f['lost v2->v3']} |"
        )
    ids = identifier_counts(pools)
    lines += ["", f"Strict-v3 matches by identifier type on entity columns (V2): {dict(ids)}."]
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
        "even where both are right under v3.",
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
        for gv in ("v1", "v2", "v3"):
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


def build_report(db: str = DEFAULT_DB, reports_dir: Path = Path("reports"), judge=None) -> str:
    gold = Gold(db)
    pools = score_bakeoff(load_evidence(), gold)
    parts = [
        "# Gold re-score: v1, v2, v3",
        "",
        "Generated by `python -m evals.rescore_v2 report`. Rules: `evals/README.md` 6g (v2) and "
        "6i (v3). v1 = `gold.jsonl` and the original comparator; v2 strict = `gold_v2.jsonl`; "
        "v3 strict = `gold_v3.jsonl` (the headline, frozen); v3 relaxed = the same gold with "
        "extra candidate columns ignored.",
        "",
        render_phase5(gold, reports_dir, judge),
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
    ap.add_argument(
        "--judge", action="store_true", help="use the local judge for judge-primary items"
    )
    ap.add_argument("--judge-model", default="llama3.1:8b")
    args = ap.parse_args(argv)
    judge = must_state.OllamaJudge(args.judge_model) if args.judge else None
    if args.part == "report":
        text = build_report(args.db, args.reports_dir, judge)
        if args.write:
            args.write.write_text(text)
            print(f"wrote {args.write}")
        else:
            print(text)
        return 0
    gold = Gold(args.db)
    if args.part == "phase5":
        print(render_phase5(gold, args.reports_dir, judge))
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
