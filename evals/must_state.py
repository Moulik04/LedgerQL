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
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PATTERNS_PATH = Path(__file__).resolve().parent / "must_state_patterns.json"
LABELS_PATH = Path(__file__).resolve().parent / "must_state_labels.jsonl"

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
    re-score never asks twice, and logged so they can be audited."""

    def __init__(self, model: str = "llama3.1:8b", host: str = "http://127.0.0.1:11434"):
        import ollama

        self.model = model
        self._client = ollama.Client(host=host)
        self._cache: dict[tuple, bool | None] = {}
        self.log: list[dict] = []

    def __call__(self, question: str, answer: str, item_text: str) -> bool | None:
        key = (question, answer, item_text)
        if key not in self._cache:
            prompt = JUDGE_PROMPT.format(question=question, answer=answer, item=item_text)
            response = self._client.generate(
                model=self.model, prompt=prompt, options={"temperature": 0, "seed": 42}
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


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["calibrate", "judge-check"])
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--judge", action="store_true", help="also ask the local judge (Ollama)")
    ap.add_argument("--judge-model", default="llama3.1:8b")
    ap.add_argument("--write", type=Path)
    args = ap.parse_args(argv)
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
    runs = {
        name: [
            json.loads(line)
            for line in (args.reports_dir / f"eval_bridges2_{name}_measured.jsonl")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        for name in ("qwen3_30b", "qwen25_32b")
    }
    questions = {}
    for line in open(Path(__file__).resolve().parent / "gold.jsonl"):
        case = json.loads(line)
        questions[case["id"]] = case["question"]
    for records in runs.values():
        for r in records:
            r["question"] = questions.get(r["id"], "")
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


if __name__ == "__main__":
    raise SystemExit(main())
