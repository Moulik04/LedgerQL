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

Abstain precision/recall here are defined identically to
`run_eval.py`'s own `compute_abstain_metrics()` (the same
`ABSTAIN_EXPECTED_BEHAVIORS = {ABSTAIN, ANSWER_WITH_ASSUMPTION}` union
set, and the same exact-reason_code-match requirement for "correct") --
by design, so the two numbers always reconcile exactly. This union set
is NOT the same thing as the "34 pure-ABSTAIN cases" used for the
always-abstain baseline below -- see that section's own comment for why
they're deliberately different denominators for different questions.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

BEHAVIOURS = ["ANSWER", "ANSWER_WITH_ASSUMPTION", "ABSTAIN"]

# Matches run_eval.py's own ABSTAIN_EXPECTED_BEHAVIORS exactly -- kept as
# a separate copy rather than an import so this stays a read-only,
# report-consuming tool with no import-time dependency on the eval
# harness (mirrors evals/validate_gold.py's own standalone-script
# convention). Update both together if run_eval.py's set ever changes.
ABSTAIN_EXPECTED_BEHAVIOURS = {"ABSTAIN", "ANSWER_WITH_ASSUMPTION"}


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
    # expected_abstains uses the SAME union set run_eval.py's
    # compute_abstain_metrics() does (ABSTAIN + ANSWER_WITH_ASSUMPTION,
    # 53 cases) -- this is what "abstain recall" is measured against
    # today, and what the committed report's own printed percentage
    # means. correct_abstain requires an exact reason_code match too,
    # matching that same function -- checking only ABSTAIN-vs-ABSTAIN
    # behaviour (as this script did before this fix) overcounts "correct"
    # for any case where the model abstained for the wrong reason.
    did_abstain = [r for r in recs if r["_observed"] == "ABSTAIN"]
    expected_abstain_recs = [r for r in recs if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS]
    correct_abstain = [
        r
        for r in did_abstain
        if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS and r["_reason"] == r["_expected_reason"]
    ]
    prec = len(correct_abstain) / len(did_abstain) if did_abstain else float("nan")
    rec_ = (
        len(correct_abstain) / len(expected_abstain_recs) if expected_abstain_recs else float("nan")
    )
    f1 = 2 * prec * rec_ / (prec + rec_) if prec and rec_ and not math.isnan(prec) else float("nan")

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
    print(f"   coverage (fraction answered)      {coverage:6.1%}")
    print(f"   abstain precision                 {prec:6.1%}")
    print(f"   abstain recall                    {rec_:6.1%}")
    print(f"   abstain F1                        {f1:6.1%}")
    print(f"   always-abstain baseline precision {baseline:6.1%}   <-- must beat this")
    if not math.isnan(prec) and prec <= baseline:
        print("   *** precision is AT OR BELOW the trivial baseline: the abstain")
        print("       decision carries no usable signal yet. Fix mechanism before tuning. ***")
    print()

    # ---- 3. false abstains by reason code ---------------------------------
    false_abstain = [r for r in did_abstain if r["_expected"] not in ABSTAIN_EXPECTED_BEHAVIOURS]
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
    # abstain-worthy case, but named a different (real, pipeline-
    # producible) reason_code than gold expected. Not counted as a false
    # abstain (the abstain decision itself was right) and not counted as
    # missed (it did abstain) -- see PHASE_5_5_MASTER_PROMPT.md Task 0.
    wrong_reason = [
        r
        for r in did_abstain
        if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS and r["_reason"] != r["_expected_reason"]
    ]
    print(f"3a. RIGHT TO ABSTAIN, WRONG REASON CODE ({len(wrong_reason)})")
    if wrong_reason:
        print(
            table(
                [
                    [r.get("id", "?"), str(r["_expected_reason"]), str(r["_reason"])]
                    for r in wrong_reason
                ],
                ["id", "expected reason", "got reason"],
            )
        )
    print()

    # ---- 3b. missed abstains ----------------------------------------------
    missed = [
        r
        for r in recs
        if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS
        and r["_observed"]
        and r["_observed"] != "ABSTAIN"
    ]
    print(f"3b. MISSED ABSTAINS ({len(missed)}) — answered a case that should have been refused")
    if missed:
        by_tier = Counter(r["_tier"] for r in missed)
        print("   by tier: " + ", ".join(f"{k}={v}" for k, v in by_tier.most_common()))
        print("   ids: " + ", ".join(r.get("id", "?") for r in missed[:20]))
    print()

    # ---- 3c. reason-code accuracy on correct abstains ----------------------
    coded = [r for r in correct_abstain if r["_expected_reason"] and r["_reason"]]
    if coded:
        right = sum(
            1 for r in coded if str(r["_reason"]).upper() == str(r["_expected_reason"]).upper()
        )
        pct = right / len(coded)
        print(f"3c. REASON-CODE ACCURACY (on correct abstains)  {right}/{len(coded)} = {pct:.0%}")
        print()

    # ---- 4. per-tier -------------------------------------------------------
    print("4. PER-TIER")
    rows = []
    for tier in sorted({r["_tier"] for r in recs}):
        t = [r for r in recs if r["_tier"] == tier]
        t_abs = [r for r in t if r["_observed"] == "ABSTAIN"]
        t_ok = [
            r
            for r in t_abs
            if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS
            and r["_reason"] == r["_expected_reason"]
        ]
        t_should = sum(1 for r in t if r["_expected"] in ABSTAIN_EXPECTED_BEHAVIOURS)
        scores = [r["_score"] for r in t if isinstance(r["_score"], int | float)]
        rows.append(
            [
                tier,
                str(len(t)),
                f"{sum(scores) / len(scores):.2f}" if scores else "-",
                f"{len(t_abs)}/{len(t)}",
                f"{len(t_ok) / len(t_abs):.0%}" if t_abs else "-",
                str(t_should),
            ]
        )
    print(table(rows, ["tier", "n", "mean score", "abstained", "abst. prec", "should abstain"]))
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
