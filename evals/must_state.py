# ruff: noqa: E501  (report format strings are single lines)
"""The `answer_must_state` grader.

Twenty-three gold cases carry rubric items: free-text sentences the answer must state (which
fiscal year was used, that a balance should not be summed, that JPMorgan has no revenue tag).
Until now nothing scored them, so "answered with the assumption stated" was unmeasured and every
assumption figure was an upper bound. This scores them.

- `evals/must_state_patterns.json` holds, for each item, regex groups written from the item's
  text alone. An item passes when **every group** has at least one alternative that matches
  (an optional `min_distinct` asks for that many different matches). This is deterministic and
  auditable, and it decides every item marked `primary: pattern`.
- A local judge (`OllamaJudge`, temperature 0) is asked "does the answer state X?". It
  **decides only items marked `primary: judge`** (the ones prose states too many ways for
  regex: the bank items, the non-additivity item); for every other item its vote is logged
  beside the pattern's and never overrides it. The grader only ever says whether the *prose*
  states something. Whether the answer's *value* is right is execution's, so an answer counts
  as "correct with the assumption stated" only when both hold (`evals/abstain_scoring.py`).
- Grading is on the text the user sees. An abstain has no answer text, and the pipeline records
  no refusal text either (only a reason code), so refusal items and "state the reason" items on
  an abstain are **not gradable** (`passed is None`), which is not a pass.

Pattern-only grading checks that something was *said*, not that it is *true*: a correct year is
the year verifier's job (`ledgerql/verify.py`, `evals/year_audit.py`).

    python -m evals.must_state calibrate   # agreement with the hand-labelled answers
    python -m evals.must_state label       # MJ labels the 14-item blind subset, one item at a time
    python -m evals.must_state agree       # MJ's blind labels (the 14-item subset) against both
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PATTERNS_PATH = Path(__file__).resolve().parent / "must_state_patterns.json"
LABELS_PATH = Path(__file__).resolve().parent / "must_state_labels.jsonl"

# The judge's prompts are short. A small context keeps the model inside the GPU memory left over when
# other applications are using it (at the default 4096 it returned empty replies under memory pressure).
JUDGE_NUM_CTX = 1024

JUDGE_PROMPT = """You are grading an answer to a question about SEC financial data.

Question: {question}

Answer: {answer}

Required statement: {item}

Does the answer state this (in any wording, explicitly and not merely by implication)? Reply with
exactly one word: YES or NO."""


@dataclass(frozen=True)
class ItemResult:
    case: str
    item: int
    passed: bool | None  # None: not gradable
    pattern_pass: bool | None
    judge_pass: bool | None
    decided_by: str  # "pattern", "judge" or "none"


def load_patterns(path: Path = PATTERNS_PATH) -> dict[str, list[dict]]:
    return json.loads(Path(path).read_text())


def compile_item(item: dict) -> list[tuple[list[re.Pattern], int]]:
    return [
        ([re.compile(rx) for rx in group["any"]], int(group.get("min_distinct", 1)))
        for group in item["groups"]
    ]


def pattern_pass(item: dict, text: str) -> bool:
    """Every group needs at least `min_distinct` different matches among its alternatives."""
    for regexes, need in compile_item(item):
        found: set[str] = set()
        for rx in regexes:
            found.update(m.group(0).lower() for m in rx.finditer(text))
        if len(found) < need:
            return False
    return True


def parse_judge_reply(reply: str | None) -> bool | None:
    if not reply:
        return None
    words = re.findall(r"[a-z]+", reply.lower())
    if not words:
        return None
    return {"yes": True, "no": False}.get(words[0])


def _text_for(item: dict, answer_text: str | None, refusal_text: str | None) -> str | None:
    surface = item["surface"]
    if surface == "answer":
        text = answer_text
    elif surface == "refusal":
        text = refusal_text
    else:  # "either": the answer if there is one, else the refusal
        text = answer_text or refusal_text
    return text or None


def grade_item(
    item: dict,
    answer_text: str | None,
    refusal_text: str | None = None,
    judge=None,
    question: str = "",
) -> ItemResult:
    case, idx = item["case"], item["item"]
    text = _text_for(item, answer_text, refusal_text)
    if text is None:
        return ItemResult(case, idx, None, None, None, "none")
    pattern = pattern_pass(item, text)
    verdict = judge(question, text, item["text"]) if judge is not None else None
    if item["primary"] == "judge":
        return ItemResult(
            case, idx, verdict, pattern, verdict, "judge" if verdict is not None else "none"
        )
    return ItemResult(case, idx, pattern, pattern, verdict, "pattern")


def grade_case(
    items: list[dict],
    answer_text: str | None,
    refusal_text: str | None = None,
    judge=None,
    question: str = "",
) -> list[ItemResult]:
    return [grade_item(i, answer_text, refusal_text, judge, question) for i in items]


def stated(results: list[ItemResult]) -> bool | None:
    """Did the text state every required item? False if any is missing; None if none is missing
    but some could not be graded, or if there is nothing to grade."""
    if not results:
        return None
    if any(r.passed is False for r in results):
        return False
    if any(r.passed is None for r in results):
        return None
    return True


class OllamaJudge:
    """A local model as the judge: temperature 0, one word back. Its votes are cached so a
    re-score never asks twice, and logged so they can be audited. Once the measurement is pinned,
    only the pinned model at the pinned digest, on the pinned Ollama, is asked
    (`evals/measurement_pin.py`)."""

    def __init__(self, model: str = "llama3.1:8b", host: str = "http://127.0.0.1:11434"):
        import ollama

        from evals import measurement_pin

        self.model = model
        self._client = ollama.Client(host=host)
        measurement_pin.require_judge(model, self._client, host)
        self._cache: dict[tuple, bool | None] = {}
        self.log: list[dict] = []

    def __call__(self, question: str, answer: str, item_text: str) -> bool | None:
        key = (question, answer, item_text)
        if key not in self._cache:
            prompt = JUDGE_PROMPT.format(question=question, answer=answer, item=item_text)
            response = self._client.generate(
                model=self.model,
                prompt=prompt,
                options={"temperature": 0, "seed": 42, "num_ctx": JUDGE_NUM_CTX},
            )
            raw = re.sub(r"<think>.*?</think>", "", response.response, flags=re.S)
            self._cache[key] = parse_judge_reply(raw)
            self.log.append({"item": item_text, "raw": response.response[:200]})
        return self._cache[key]


def load_labels(path: Path = LABELS_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def calibrate(
    records_by_run: dict[str, list[dict]],
    patterns: dict[str, list[dict]],
    labels: list[dict],
    judge=None,
) -> dict:
    """Agreement of the grader (and, separately, the judge) with hand labels. A label for a record
    with no answer text is skipped: there is nothing to grade."""
    by_key = {(run, r["id"]): r for run, records in records_by_run.items() for r in records}
    rows = []
    for lab in labels:
        rec = by_key.get((lab["run"], lab["case"]))
        item = patterns[lab["case"]][lab["item"]]
        if rec is None or not rec.get("answer"):
            continue
        res = grade_item(item, rec["answer"], None, judge, rec.get("question", ""))
        rows.append({**lab, "graded": res.passed, "pattern": res.pattern_pass,
                     "judge": res.judge_pass, "decided_by": res.decided_by})  # fmt: skip
    gradable = [r for r in rows if r["graded"] is not None]
    out = {
        "n": len(rows),
        "agree": sum(r["graded"] == r["label"] for r in gradable),
        "false_pass": sum(r["graded"] is True and r["label"] is False for r in gradable),
        "false_fail": sum(r["graded"] is False and r["label"] is True for r in gradable),
        "ungradable": len(rows) - len(gradable),
        "disagreements": [r for r in gradable if r["graded"] != r["label"]],
        "rows": rows,
    }
    voted = [r for r in rows if r["judge"] is not None]
    if judge is not None:
        out["judge"] = {
            "n": len(voted),
            "agree": sum(r["judge"] == r["label"] for r in voted),
            "unparsed": sum(r["judge"] is None for r in rows),
        }
    return out


def _format_calibration(out: dict, title: str) -> str:
    lines = [
        title,
        "",
        f"{out['n']} hand labels on real answers; grader agrees on {out['agree']} of "
        f"{out['n'] - out['ungradable']} gradable (false passes {out['false_pass']}, false fails "
        f"{out['false_fail']}, not gradable {out['ungradable']}).",
    ]
    if "judge" in out:
        j = out["judge"]
        lines.append(
            f"The judge (logged apart, decides only `primary: judge` items) agrees with the labels "
            f"on {j['agree']} of {j['n']} votes ({j['unparsed']} unparsed)."
        )
    lines += [
        "",
        "| run | case | item | label | pattern | judge | decides | graded | note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in out["rows"]:
        lines.append(
            f"| {r['run']} | {r['case']} | {r['item']} | {r['label']} | {r['pattern']} | "
            f"{r['judge']} | {r['decided_by']} | {r['graded']} | {r['note'][:70]} |"
        )
    return "\n".join(lines) + "\n"


def _load_runs(reports_dir: Path) -> dict[str, list[dict]]:
    """The two measured Phase 5 runs, each record carrying its question."""
    questions = {}
    for line in open(Path(__file__).resolve().parent / "gold.jsonl"):
        case = json.loads(line)
        questions[case["id"]] = case["question"]
    runs = {}
    for name in ("qwen3_30b", "qwen25_32b"):
        path = reports_dir / f"eval_bridges2_{name}_measured.jsonl"
        runs[name] = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        for r in runs[name]:
            r["question"] = questions.get(r["id"], "")
    return runs


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "command", choices=["calibrate", "judge-check", "blind", "blind-subset", "label", "agree"]
    )
    ap.add_argument(
        "--blind-file",
        type=Path,
        help="default: the full sheet for `blind`, the 14-item subset for the other three",
    )
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--judge", action="store_true", help="also ask the local judge (Ollama)")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
    if args.command == "label":
        sheet = args.blind_file or SUBSET_PATH
        try:
            done = label_sheet(sheet, ask=input, show=print)
        except (EOFError, KeyboardInterrupt):
            print("\nstopped: the answers given so far are saved; run it again to continue")
            return 1
        print(f"\n{done} labelled in this run; no row of {sheet.name} is blank")
        return 0
    if args.command in ("blind", "blind-subset", "agree"):
        runs, patterns = _load_runs(args.reports_dir), load_patterns()
        blind_file = args.blind_file or (BLIND_PATH if args.command == "blind" else SUBSET_PATH)
        if args.command in ("blind", "blind-subset"):
            build = build_blind if args.command == "blind" else build_blind_subset
            rows = build(runs, patterns, load_labels())
            blind_file.write_text("".join(json.dumps(r) + "\n" for r in rows))
            print(f"wrote {blind_file}: {len(rows)} rows, no labels")
            return 0
        blind = [json.loads(x) for x in blind_file.read_text().splitlines() if x.strip()]
        judge = OllamaJudge(args.judge_model) if args.judge else None
        text = _format_agreement(agreement(blind, load_labels(), runs, patterns, judge))
        if args.write:
            args.write.write_text(text)
        print(text)
        return 0
    if args.command == "judge-check":
        checks = [json.loads(x) for x in CHECKS_PATH.read_text().splitlines() if x.strip()]
        patterns = load_patterns()
        judge = OllamaJudge(args.judge_model)
        by_judge = judge_check(checks, patterns, judge)
        by_pattern = judge_check(checks, patterns, _pattern_voter(patterns, checks))
        text = (
            "# answer_must_state: judge and pattern on constructed answers\n\n"
            f"{len(checks)} constructed answers (10 that state the item, 10 that do not), "
            f"judge `{args.judge_model}`.\n\n| grader | recall | precision | false negatives | "
            "false positives | unparsed |\n|---|---|---|---|---|---|\n"
            + "".join(
                f"| {name} | {r['recall']} | {r['precision']} | {r['false_negatives']} | "
                f"{r['false_positives']} | {r['unparsed']} |\n"
                for name, r in (("judge", by_judge), ("pattern", by_pattern))
            )
        )
        if args.write:
            args.write.write_text(text)
        print(text)
        return 0
    runs = _load_runs(args.reports_dir)
    judge = OllamaJudge(args.judge_model) if args.judge else None
    out = calibrate(runs, load_patterns(), load_labels(), judge)
    text = _format_calibration(out, "# answer_must_state: calibration against hand labels")
    if args.write:
        args.write.write_text(text)
    print(text)
    return 0


CHECKS_PATH = Path(__file__).resolve().parent / "must_state_judge_checks.jsonl"


def _pattern_voter(patterns: dict[str, list[dict]], checks: list[dict]):
    """The pattern result as a `judge(question, answer, item_text)` callable, for comparison."""
    lookup = {item["text"]: item for items in patterns.values() for item in items}
    return lambda question, answer, item_text: pattern_pass(lookup[item_text], answer)


def judge_check(checks: list[dict], patterns: dict[str, list[dict]], judge) -> dict:
    """Recall and precision of a judge on constructed answers that do and do not state an item
    (`must_state_judge_checks.jsonl`, written from the rubric text before the judge was run).
    Real answers rarely state the judge-decided items, so their positives cannot test it."""
    tp = fp = fn = tn = unparsed = 0
    for c in checks:
        item = patterns[c["case"]][c["item"]]
        vote = judge(c["question"], c["answer"], item["text"])
        if vote is None:
            unparsed += 1
            continue
        if c["label"]:
            tp += vote
            fn += not vote
        else:
            fp += vote
            tn += not vote
    positives, voted_pos = tp + fn, tp + fp
    return {
        "n": len(checks),
        "recall": tp / positives if positives else None,
        "precision": tp / voted_pos if voted_pos else None,
        "false_negatives": fn,
        "false_positives": fp,
        "unparsed": unparsed,
    }


BLIND_PATH = Path(__file__).resolve().parent / "must_state_labels_blind.jsonl"


def build_blind(
    records_by_run: dict[str, list[dict]],
    patterns: dict[str, list[dict]],
    labels: list[dict],
    seed: int = 20260930,
) -> list[dict]:
    """The same answers and rubric items as `labels`, in shuffled order, with the full answer text
    and no label or note, for a second person to label without seeing the first labeller's."""
    import random

    by_key = {(run, r["id"]): r for run, records in records_by_run.items() for r in records}
    rows = []
    for lab in labels:
        rec = by_key[(lab["run"], lab["case"])]
        item = patterns[lab["case"]][lab["item"]]
        rows.append(
            {
                "answer_id": f"{lab['run']}:{lab['case']}:{lab['item']}",
                "run": lab["run"],
                "case": lab["case"],
                "item": lab["item"],
                "question": rec.get("question", ""),
                "item_text": item["text"],
                "answer": rec["answer"],
                "label": None,
                "note": "",
            }
        )
    random.Random(seed).shuffle(rows)
    return rows


SUBSET_PATH = Path(__file__).resolve().parent / "must_state_labels_blind_subset.jsonl"


def is_judgement_call(label: dict) -> bool:
    """A label the first labeller marked as one a careful reader could give either way."""
    return label.get("note", "").startswith("JUDGEMENT CALL")


def subset_labels(labels: list[dict], n_random: int = 10, seed: int = 20261004) -> list[dict]:
    """The labels the human check covers: every judgement call, and `n_random` of the others drawn
    at random. The two parts are different things: the first is all of the hard items, the second
    is a sample that speaks for the rest."""
    import random

    rest = [lab for lab in labels if not is_judgement_call(lab)]
    return [lab for lab in labels if is_judgement_call(lab)] + random.Random(seed).sample(
        rest, n_random
    )


def build_blind_subset(
    records_by_run: dict[str, list[dict]],
    patterns: dict[str, list[dict]],
    labels: list[dict],
    n_random: int = 10,
    seed: int = 20261004,
) -> list[dict]:
    """A blind sheet for `subset_labels`: the same rows as the full sheet's, shuffled together, so
    nothing in it says which rows are the judgement calls."""
    return build_blind(records_by_run, patterns, subset_labels(labels, n_random, seed), seed)


def label_sheet(path: Path = SUBSET_PATH, ask=input, show=print) -> int:
    """Label a blind sheet by hand. Each row that has no label yet is shown alone (the question,
    the answer as the user saw it, the rubric item) and answered y or n, and the answer is written
    to the file at once, as true or false. Stopping part-way loses nothing, and a second run asks
    only for the rows still blank. Returns how many rows were labelled in this run."""
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    todo = [r for r in rows if r["label"] is None]
    for n, row in enumerate(todo, len(rows) - len(todo) + 1):
        show(
            f"\n[{n} of {len(rows)}]\nQuestion:   {row['question']}\n"
            f"Answer:     {row['answer']}\nMust state: {row['item_text']}"
        )
        reply = ""
        while reply not in ("y", "yes", "n", "no"):
            reply = ask("Does the answer state it? [y/n] ").strip().lower()
        row["label"] = reply.startswith("y")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(todo)


_FINAL = re.compile(r"FINAL\b[^:]*:\s*(not stated|stated)\b")


def final_call(row: dict) -> bool | None:
    """MJ's adjudicated call on a blind row, written at the start of its note after the
    disagreements were read: `FINAL (MJ, <date>): stated. <why>` or `...: not stated. <why>`.
    None: the row was not adjudicated and its blind label stands. The label itself is never
    edited, so the blind agreement can always be recomputed."""
    found = _FINAL.match(row.get("note") or "")
    return None if found is None else found.group(1) == "stated"


def agreement(
    blind: list[dict],
    claude_labels: list[dict],
    records_by_run: dict[str, list[dict]],
    patterns: dict[str, list[dict]],
    judge=None,
) -> dict:
    """MJ's blind labels against the grader and against the first labeller, per item and overall,
    with every disagreement listed for adjudication. Nothing is adjusted here. Once a row's note
    carries a final call (`final_call`), the adjudicated outcome is reported beside the blind
    figures, which do not change."""
    claude = {(r["run"], r["case"], r["item"]): r["label"] for r in claude_labels}
    calls = {(r["run"], r["case"], r["item"]) for r in claude_labels if is_judgement_call(r)}
    by_key = {(run, r["id"]): r for run, recs in records_by_run.items() for r in recs}
    rows, unlabelled = [], 0
    for b in blind:
        if b["label"] is None:
            unlabelled += 1
            continue
        key = (b["run"], b["case"], b["item"])
        rec = by_key[(b["run"], b["case"])]
        graded = grade_item(
            patterns[b["case"]][b["item"]], rec["answer"], None, judge, rec.get("question", "")
        )
        rows.append(
            {
                "run": b["run"], "case": b["case"], "item": b["item"], "mj": b["label"],
                "claude": claude.get(key), "grader": graded.passed,
                "pattern": graded.pattern_pass, "judge": graded.judge_pass,
                "decided_by": graded.decided_by, "mj_note": b.get("note", ""),
                "answer": rec["answer"], "judgement_call": key in calls,
                "adjudicated": final_call(b) is not None,
                "final": b["label"] if final_call(b) is None else final_call(b),
            }
        )  # fmt: skip

    def tally(field, against="mj"):
        gradable = [r for r in rows if r[field] is not None]
        return {"n": len(gradable), "agree": sum(r[field] == r[against] for r in gradable)}

    def part(is_call: bool, of: int) -> dict:
        mine = [r for r in rows if r["judgement_call"] is is_call]
        return {
            "n": len(mine),
            "of": of,
            "mj_claude": sum(r["claude"] == r["mj"] for r in mine),
            "mj_grader": sum(r["grader"] == r["mj"] for r in mine),
        }

    per_item: dict[tuple, dict] = {}
    for r in rows:
        cell = per_item.setdefault((r["case"], r["item"]), {"n": 0, "mj_claude": 0, "mj_grader": 0})
        cell["n"] += 1
        cell["mj_claude"] += r["claude"] == r["mj"]
        cell["mj_grader"] += r["grader"] == r["mj"]
    graded = [r for r in rows if r["grader"] is not None]
    adjudicated = {
        "n": sum(r["adjudicated"] for r in rows),
        # the blind labels the grader disagreed with, and how many of those MJ took back
        "differed_from_grader": sum(r["grader"] != r["mj"] for r in graded),
        "to_grader": sum(r["grader"] != r["mj"] and r["grader"] == r["final"] for r in graded),
        "final_vs_grader": tally("grader", "final"),
        "final_vs_claude": tally("claude", "final"),
        "false_fails": [r for r in graded if r["final"] is True and r["grader"] is False],
        "false_passes": [r for r in graded if r["final"] is False and r["grader"] is True],
        "rows": [r for r in rows if r["adjudicated"]],
    }
    return {
        "n": len(rows),
        "unlabelled": unlabelled,
        "adjudicated": adjudicated,
        # What the human check covers: the labels are a subset of the first labeller's, and not a
        # uniform one (every judgement call, a random draw of the rest).
        "first_labeller_total": len(claude_labels),
        "judgement_calls": part(True, len(calls)),
        "others": part(False, len(claude_labels) - len(calls)),
        "mj_vs_claude": tally("claude"),
        "mj_vs_grader": tally("grader"),
        "per_item": per_item,
        "disagreements": [r for r in rows if r["claude"] != r["mj"] or r["grader"] != r["mj"]],
    }


def _format_adjudication(adj: dict, share) -> list[str]:
    """The outcome after MJ re-read the disagreements: how many blind labels MJ took back, the
    final calls against the grader and the first labeller, and what stands against the grader."""
    took_back = adj["to_grader"]

    def listed(rows: list[dict]) -> list[str]:
        return [f"- {r['run']} {r['case']}[{r['item']}]: {r['answer']}" for r in rows] or ["- none"]

    return [
        "## After adjudication",
        "",
        f"MJ re-read the disagreements and wrote a final call in the note of {adj['n']} rows. The "
        "blind labels are kept as first given and every figure above is computed from them. MJ's "
        f"blind label differed from the grader on {adj['differed_from_grader']} gradable items: "
        f"**{took_back} {'was' if took_back == 1 else 'were'} resolved in the grader's favour on "
        "re-reading** (the blind label was wrong and the grader right), and "
        f"{adj['differed_from_grader'] - took_back} stand against the grader. **Final call vs the "
        f"grader:** {share(adj['final_vs_grader'])} gradable. **Final call vs the first "
        f"labeller:** {share(adj['final_vs_claude'])}.",
        "",
        "The grader's false fails by the final calls (stated, and graded not stated). The patterns "
        "are left as they are and these are listed in `evals/KNOWN_GOLD_ISSUES.md`:",
        "",
        *listed(adj["false_fails"]),
        "",
        "Its false passes by the final calls (not stated, and graded stated):",
        "",
        *listed(adj["false_passes"]),
        "",
        "| run | case | item | blind label | final call | grader | first labeller | MJ's note |",
        "|---|---|---|---|---|---|---|---|",
        *(
            f"| {r['run']} | {r['case']} | {r['item']} | {r['mj']} | {r['final']} | {r['grader']} "
            f"| {r['claude']} | {r['mj_note']} |"
            for r in adj["rows"]
        ),
        "",
    ]


def _format_agreement(out: dict) -> str:
    c, g = out["mj_vs_claude"], out["mj_vs_grader"]
    jc, rest = out["judgement_calls"], out["others"]
    adj = out["adjudicated"]

    def share(t: dict) -> str:
        return f"{t['agree']} of {t['n']}" + (f" ({t['agree'] / t['n']:.0%})" if t["n"] else "")

    lines = [
        "# answer_must_state: MJ's blind labels against the grader and the first labeller",
        "",
        f"{out['n']} labelled ({out['unlabelled']} left blank), of the {out['first_labeller_total']} "
        f"items the first labeller labelled. **MJ vs the grader:** {share(g)} gradable. **MJ vs the "
        f"first labeller:** {share(c)}. "
        + (
            "These are the labels as MJ first gave them, blind; what re-reading changed is under "
            "*After adjudication*."
            if adj["n"]
            else "Patterns are not adjusted until MJ has adjudicated the disagreements below."
        ),
        "",
        "## What the check covers",
        "",
        "| part | labelled by MJ | MJ = first labeller | MJ = grader |",
        "|---|---|---|---|",
        f"| items the first labeller marked a judgement call | {jc['n']} of {jc['of']} | "
        f"{jc['mj_claude']} | {jc['mj_grader']} |",
        f"| the other items | {rest['n']} of {rest['of']} | {rest['mj_claude']} | {rest['mj_grader']} |",
        "",
    ]
    if rest["n"] < rest["of"]:
        lines += [
            f"The {out['first_labeller_total'] - jc['n'] - rest['n']} items MJ did not label carry "
            "the first labeller's label only. The judgement calls are over-represented on purpose, "
            "so the overall rate above is not an estimate for all "
            f"{out['first_labeller_total']}: the second row is the sample that speaks for the "
            "other items.",
            "",
        ]
    if adj["n"]:
        lines += _format_adjudication(adj, share)
    lines += [
        "## Per item",
        "",
        "| case | item | n | MJ = first labeller | MJ = grader |",
        "|---|---|---|---|---|",
    ]
    for (case, item), cell in sorted(out["per_item"].items()):
        lines.append(
            f"| {case} | {item} | {cell['n']} | {cell['mj_claude']} | {cell['mj_grader']} |"
        )
    lines += ["", "## Every disagreement" + ("" if adj["n"] else " (for MJ to adjudicate)"), ""]
    for r in out["disagreements"]:
        lines += [
            f"### {r['run']} {r['case']}[{r['item']}]: MJ {r['mj']}, first labeller {r['claude']}, "
            f"grader {r['grader']} (pattern {r['pattern']}, judge {r['judge']}, decided by {r['decided_by']})",
            "",
            f"Answer: {r['answer']}",
            "",
            f"MJ's note: {r['mj_note'] or '(none)'}",
            "",
        ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
