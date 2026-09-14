"""Decompose abstain behaviour from an existing eval run.

    python evals/diagnose_abstains.py reports/eval_<date>.jsonl --gold evals/gold.jsonl

Reads the per-case records `make eval` already writes and answers the
questions that a single pooled "abstain precision" number hides:

  1. Where do abstains actually land? (3x3 expected x observed matrix)
  2. Is abstain precision better than the trivial always-abstain baseline?
  3. Which reason codes drive the FALSE abstains? (the actionable table)
  4. Which tiers are bleeding? (pooled precision hides per-tier collapse)
  5. Is confidence predictive at all? (separation + ECE + twin consistency)
  6. Is the bottleneck generation or selection? (pass@N oracle, if candidates
     were logged)

Field names follow evals/README.md section 3's aspirational full schema
(`observed_behavior`, `score`, per-candidate logs, ...) where that data
exists; anything missing is reported as "not logged" rather than crashing.
But the *real* per-case records `run_eval.py` writes today only carry
`answer`/`reason_code`/`execution_correct` (Core-only scope, no
`ANSWER_WITH_ASSUMPTION` output state yet -- see
PHASE_5_5_MASTER_PROMPT.md Task 2) -- so "observed behaviour" and an
approximate "score" are derived from those real fields when the
aspirational ones aren't present. See PHASE_5_5_MASTER_PROMPT.md Task 0
and DECISIONS.md for why this reconciliation matters and what it found.

Abstain precision/recall/reason-code-accuracy here are computed by the
exact same `evals/abstain_scoring.py` module `run_eval.py` itself uses --
a real import, not a second copy -- so the two always reconcile exactly.
PHASE_5_5_AMENDMENT_1.md found `run_eval.py`'s original single "abstain
precision" number silently conflated two different questions (was
abstaining the right decision; was the reason code also right); this
tool reports both ("decision" and "strict"), plus `accept_alternatives`-
aware reason-code accuracy, never a single bare number again.

The union set (53 cases: ABSTAIN + ANSWER_WITH_ASSUMPTION) used for
`abstain_recall_*`'s denominator is NOT the same thing as the "34
pure-ABSTAIN cases" used for the always-abstain baseline below -- see
that section's own comment for why they're deliberately different
denominators for different questions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Same bootstrap as run_eval.py, for the same reason: running this
# directly (`python evals/diagnose_abstains.py`) sets sys.path[0] to
# evals/ itself, not the project root, so `evals.abstain_scoring` (a
# sibling module in this same directory) can't resolve as a package-
# qualified import without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.abstain_scoring import (  # noqa: E402
    ABSTAIN_EXPECTED_BEHAVIORS,
    acceptable_reason_codes,
    compute_abstain_metrics,
)

BEHAVIOURS = ["ANSWER", "ANSWER_WITH_ASSUMPTION", "ABSTAIN"]


def load_jsonl(path: Path) -> list[dict]:
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"warning: {path.name} line {n} unparseable ({e})", file=sys.stderr)
    return out


def get(rec: dict, *names, default=None):
    """Tolerate naming drift between the spec and what was implemented."""
    for n in names:
        if n in rec and rec[n] is not None:
            return rec[n]
    return default


def norm_behaviour(v) -> str | None:
    if v is None:
        return None
    s = str(v).upper()
    if "ABSTAIN" in s or "REFUS" in s:
        return "ABSTAIN"
    if "ASSUMPTION" in s or "CAVEAT" in s:
        return "ANSWER_WITH_ASSUMPTION"
    if "ANSWER" in s:
        return "ANSWER"
    return s


def infer_observed_behaviour(rec: dict) -> str | None:
    """The real bug this whole script had: it only ever looked for an
    `observed_behavior`/`observed`/`behavior` field, which doesn't exist
    in any real per-case record run_eval.py writes today -- so this was
    always None, and every downstream metric silently computed over zero
    matching records (nan/all-zero output, not an error). Falls back to
    deriving it from the real `answer` field: today's pipeline only has
    two terminal states (ANSWER or ABSTAIN-with-a-reason -- the third,
    ANSWER_WITH_ASSUMPTION, is not emittable yet, see
    PHASE_5_5_MASTER_PROMPT.md Task 2), so that column of every table
    below is legitimately all-zero until that task lands, not a bug.
    Checks the explicit field first, for forward-compatibility once a
    later task adds one.
    """
    explicit = get(rec, "observed_behavior", "observed", "behavior")
    if explicit is not None:
        return norm_behaviour(explicit)
    return "ABSTAIN" if rec.get("answer") is None else "ANSWER"


def infer_score(rec: dict) -> float | None:
    """Same pattern as infer_observed_behaviour: evals/README.md section 3
    specifies a `score` in {1, 0.5, 0} field that doesn't exist in real
    records yet (no rubric-pass-check infrastructure to compute the 0.5
    case). run_eval.py does write `execution_correct` for
    expected-ANSWER cases specifically -- use that as a real, if
    coarser (no 0.5), approximation where the real field is absent.
    Returns None (not logged) for abstain-expected cases, where there is
    currently no equivalent real signal to approximate a score from.
    """
    explicit = get(rec, "score")
    if explicit is not None:
        return explicit
    if "execution_correct" in rec:
        return 1.0 if rec["execution_correct"] else 0.0
    return None


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]

    def line(r):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r))

    sep = "  ".join("-" * w for w in widths)
    return "\n".join([line(headers), sep] + [line(r) for r in rows])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_jsonl")
    ap.add_argument("--gold", default="evals/gold.jsonl")
    ap.add_argument("--bins", type=int, default=10)
    args = ap.parse_args(argv)

    recs = load_jsonl(Path(args.eval_jsonl))
    gold = {c["id"]: c for c in load_jsonl(Path(args.gold))}
    if not recs:
        sys.exit("no eval records found")

    # ---- join gold onto records -------------------------------------------
    for r in recs:
        g = gold.get(r.get("id"), {})
        r["_expected"] = norm_behaviour(get(r, "expected") or g.get("expected"))
        r["_observed"] = infer_observed_behaviour(r)
        r["_tier"] = get(r, "tier") or g.get("tier", "?")
        r["_score"] = infer_score(r)
        r["_reason"] = get(r, "observed_reason", "reason_code", "reason")
        r["_conf"] = get(r, "confidence", "conf")
        r["_expected_reason"] = g.get("reason_code")

    n = len(recs)
    print(f"=== {args.eval_jsonl} — {n} cases ===\n")

    # ---- 1. confusion matrix ----------------------------------------------
    cm = Counter((r["_expected"], r["_observed"]) for r in recs if r["_observed"])
    rows = []
    for exp_b in BEHAVIOURS:
        row = [exp_b]
        for obs_b in BEHAVIOURS:
            row.append(cm.get((exp_b, obs_b), 0))
        row.append(sum(cm.get((exp_b, o), 0) for o in BEHAVIOURS))
        rows.append(row)
    print("1. EXPECTED (rows) x OBSERVED (cols)")
    print(
        table(
            [[str(c) for c in r] for r in rows],
            ["expected \\ observed", "ANSWER", "W/ASSUMPTION", "ABSTAIN", "total"],
        )
    )
    print()

    # ---- 2. abstain metrics vs baseline -----------------------------------
    # Computed by the same evals/abstain_scoring.py compute_abstain_metrics()
    # run_eval.py itself calls -- a real shared import, not a second
    # reimplementation, so these numbers always reconcile with the
    # committed report exactly. per_case/cases_by_id here use the real
    # `answer`/`reason_code` fields directly (not the _observed/_reason
    # display aliases this script builds for its own tables below), since
    # that's the interface compute_abstain_metrics expects.
    per_case = [
        {"id": r.get("id"), "answer": r.get("answer"), "reason_code": r.get("reason_code")}
        for r in recs
    ]
    metrics = compute_abstain_metrics(per_case, gold)

    did_abstain = [r for r in recs if r["_observed"] == "ABSTAIN"]
    decision_correct = [r for r in did_abstain if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIORS]
    strict_ids = {
        r.get("id")
        for r in did_abstain
        if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIORS
        and r["_reason"] in acceptable_reason_codes(gold.get(r.get("id"), {}))
    }

    # The always-abstain baseline is a DIFFERENT question ("if the system
    # refused every single question, how good would that look?") and
    # deliberately uses a different, narrower denominator: only pure
    # ABSTAIN-expected cases (34) can ever score "correct" under an
    # always-abstain policy, since a real abstain always sets some
    # non-None reason_code, and gold's own reason_code for
    # ANSWER_WITH_ASSUMPTION cases is (with one exception) None -- see
    # DECISIONS.md's 2026-09-11 entry, "structurally unreachable" cases.
    # Mixing this 34-based ceiling into the 53-based recall denominator
    # above would silently change what "abstain recall" means from what
    # the committed report already states.
    pure_abstain_recs = [r for r in recs if r["_expected"] == "ABSTAIN"]
    baseline = len(pure_abstain_recs) / n
    coverage = 1 - len(did_abstain) / n

    print("2. ABSTAIN BEHAVIOUR")
    print("   decision = was abstaining the right call, any reason code;")
    print("   strict = right call AND an acceptable reason code (gold's own")
    print("   reason_code, or an ABSTAIN:CODE entry in accept_alternatives)")
    print("   -- PHASE_5_5_AMENDMENT_1.md part A: never report a single bare")
    print("   'abstain precision' again, it silently conflated these two.")
    print(f"   coverage (fraction answered)          {coverage:6.1%}")
    print(f"   abstain precision (decision)          {metrics['abstain_precision_decision']:6.1%}")
    print(f"   abstain precision (strict)            {metrics['abstain_precision_strict']:6.1%}")
    print(f"   abstain recall (decision)             {metrics['abstain_recall_decision']:6.1%}")
    print(f"   abstain recall (strict)               {metrics['abstain_recall_strict']:6.1%}")
    print(f"   reason-code accuracy                  {metrics['reason_code_accuracy']:6.1%}")
    print(f"   always-abstain baseline precision     {baseline:6.1%}   <-- must beat this")
    if metrics["abstain_precision_strict"] <= baseline:
        print("   *** strict precision is AT OR BELOW the trivial baseline: the")
        print("       abstain decision carries no usable signal yet. ***")
    print()

    # ---- 3. false abstains by reason code ---------------------------------
    false_abstain = [r for r in did_abstain if r["_expected"] not in ABSTAIN_EXPECTED_BEHAVIORS]
    print(f"3. FALSE ABSTAINS ({len(false_abstain)}) — abstained on an answerable case")
    if false_abstain:
        by_reason = Counter(r["_reason"] or "(none logged)" for r in false_abstain)
        print(
            table(
                [[k, str(v), f"{v / len(false_abstain):.0%}"] for k, v in by_reason.most_common()],
                ["reason code", "n", "share"],
            )
        )
        print("\n   example ids per reason:")
        ex = defaultdict(list)
        for r in false_abstain:
            ex[r["_reason"] or "(none logged)"].append(r.get("id", "?"))
        for k, ids in sorted(ex.items(), key=lambda kv: -len(kv[1])):
            print(f"     {k:<22} {', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}")
    else:
        print("   none — precision is limited by something else")
    print()

    # ---- 3a. abstained on the right case, wrong reason ---------------------
    # A case genuinely worth its own bucket, distinct from both "correct"
    # and "false abstain" above: the model correctly judged this an
    # abstain-worthy case, but named a reason code not in gold's
    # acceptable set (its own reason_code plus any accept_alternatives --
    # PHASE_5_5_AMENDMENT_1.md part B). Not counted as a false abstain
    # (the abstain decision itself was right) and not counted as missed
    # (it did abstain) -- its own category, this is reason_code_accuracy's
    # complement (decision_correct - strict_correct from section 2).
    wrong_reason_ids = {r.get("id") for r in decision_correct} - strict_ids
    wrong_reason = [r for r in decision_correct if r.get("id") in wrong_reason_ids]
    print(f"3a. RIGHT TO ABSTAIN, WRONG REASON CODE ({len(wrong_reason)})")
    if wrong_reason:
        print(
            table(
                [
                    [
                        r.get("id", "?"),
                        "/".join(sorted(acceptable_reason_codes(gold.get(r.get("id"), {})))) or "-",
                        str(r["_reason"]),
                    ]
                    for r in wrong_reason
                ],
                ["id", "acceptable reason(s)", "got reason"],
            )
        )
    print()

    # ---- 3b. missed abstains ----------------------------------------------
    missed = [
        r
        for r in recs
        if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIORS
        and r["_observed"]
        and r["_observed"] != "ABSTAIN"
    ]
    print(f"3b. MISSED ABSTAINS ({len(missed)}) — answered a case that should have been refused")
    if missed:
        by_tier = Counter(r["_tier"] for r in missed)
        print("   by tier: " + ", ".join(f"{k}={v}" for k, v in by_tier.most_common()))
        print("   ids: " + ", ".join(r.get("id", "?") for r in missed[:20]))
    print()

    # ---- 4. per-tier -------------------------------------------------------
    # "abst. prec (dec/strict)" mirrors section 2's decision/strict split
    # per tier -- a pooled precision can hide a tier that's collapsed
    # under one definition but not the other.
    print("4. PER-TIER")
    rows = []
    for tier in sorted({r["_tier"] for r in recs}):
        t = [r for r in recs if r["_tier"] == tier]
        t_abs = [r for r in t if r["_observed"] == "ABSTAIN"]
        t_decision_ok = [r for r in t_abs if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIORS]
        t_strict_ok = [r for r in t_decision_ok if r.get("id") in strict_ids]
        t_should = sum(1 for r in t if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIORS)
        scores = [r["_score"] for r in t if isinstance(r["_score"], int | float)]
        rows.append(
            [
                tier,
                str(len(t)),
                f"{sum(scores) / len(scores):.2f}" if scores else "-",
                f"{len(t_abs)}/{len(t)}",
                f"{len(t_decision_ok) / len(t_abs):.0%}" if t_abs else "-",
                f"{len(t_strict_ok) / len(t_abs):.0%}" if t_abs else "-",
                str(t_should),
            ]
        )
    print(
        table(
            rows,
            [
                "tier",
                "n",
                "mean score",
                "abstained",
                "prec (decision)",
                "prec (strict)",
                "should abstain",
            ],
        )
    )
    print()

    # ---- 5. confidence -----------------------------------------------------
    conf = [r for r in recs if isinstance(r["_conf"], int | float)]
    print("5. CONFIDENCE")
    if not conf:
        print("   not logged — the confidence model (README section 6) appears unbuilt.")
        print("   Without it there is no threshold to tune and abstains must be")
        print("   coming from guardrails/consensus alone. This is the thing to build.")
    else:
        scored = [r for r in conf if r["_score"] is not None]
        if not scored:
            print("   confidence is logged but no score (real or execution_correct-")
            print("   derived) exists to compare it against for these cases.")
        else:
            correct = [r["_conf"] for r in scored if r["_score"] == 1]
            wrong = [r["_conf"] for r in scored if r["_score"] != 1]
            mc = sum(correct) / len(correct) if correct else float("nan")
            mw = sum(wrong) / len(wrong) if wrong else float("nan")
            print(f"   mean confidence | correct  {mc:.3f}   (n={len(correct)})")
            print(f"   mean confidence | wrong    {mw:.3f}   (n={len(wrong)})")
            print(f"   separation                 {mc - mw:+.3f}   <-- near 0 means uninformative")
            bins = [[] for _ in range(args.bins)]
            for r in scored:
                idx = min(int(r["_conf"] * args.bins), args.bins - 1)
                bins[idx].append(r)
            ece = 0.0
            brows = []
            for i, b in enumerate(bins):
                if not b:
                    continue
                acc = sum(1 for r in b if r["_score"] == 1) / len(b)
                avg = sum(r["_conf"] for r in b) / len(b)
                ece += len(b) / len(scored) * abs(acc - avg)
                brows.append(
                    [
                        f"{i / args.bins:.1f}-{(i + 1) / args.bins:.1f}",
                        str(len(b)),
                        f"{avg:.2f}",
                        f"{acc:.2f}",
                        f"{acc - avg:+.2f}",
                    ]
                )
            print(f"   ECE                        {ece:.3f}   (target < 0.05)")
            print(table(brows, ["bin", "n", "mean conf", "accuracy", "gap"]))
        # twin consistency: independent of score/observed-behaviour fixes
        # above, uses confidence + gold's own difficulty field directly.
        twins = [(c["id"], c["twin"]) for c in gold.values() if c.get("twin")]
        seen, ok, tot = set(), 0, 0
        cmap = {r["id"]: r["_conf"] for r in conf if "id" in r}
        for a, b in twins:
            if (b, a) in seen:
                continue
            seen.add((a, b))
            if a in cmap and b in cmap:
                tot += 1
                easy, hard = (
                    (a, b)
                    if gold[a].get("difficulty", 0) <= gold[b].get("difficulty", 0)
                    else (b, a)
                )
                if cmap[easy] >= cmap[hard]:
                    ok += 1
        if tot:
            print(f"   twin consistency           {ok}/{tot} pairs ordered correctly")
    print()

    # ---- 6. oracle ceiling -------------------------------------------------
    print("6. GENERATION vs SELECTION")
    cand_field = next(
        (f for f in ("candidates", "sql_candidates", "samples") if any(f in r for r in recs)), None
    )
    if not cand_field:
        print("   per-candidate results not logged. Log each sampled candidate's")
        print("   execution-match flag and re-run: if pass@N is far above pass@1,")
        print("   the bottleneck is SELECTION (voting/confidence), not generation —")
        print("   which is exactly the case where a bigger model won't help.")
    else:
        answerable = [r for r in recs if r["_expected"] == "ANSWER" and r["_score"] is not None]
        p1 = (
            sum(1 for r in answerable if r["_score"] == 1) / len(answerable)
            if answerable
            else float("nan")
        )
        pn = (
            sum(
                1 for r in answerable if any(c.get("exec_match") for c in (r.get(cand_field) or []))
            )
            / len(answerable)
            if answerable
            else float("nan")
        )
        print(f"   pass@1 (as scored)   {p1:.1%}")
        print(f"   pass@N (oracle)      {pn:.1%}")
        print(f"   selection headroom   {pn - p1:+.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
