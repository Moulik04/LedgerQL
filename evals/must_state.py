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
