# ruff: noqa: E501  (template tables and comments are kept on single lines)
"""The held-out gold set's tier/count template and its seeded company assignment.

The protocol (evals/HELDOUT_PROTOCOL.md) needs the held-out questions written blind: without
reference to any model output, and without the question writer or the gold writer choosing which
companies to ask about (a favourite company is a company the entity linker may already handle).
So which company sits in which question slot is drawn here, from a committed seed, stratified
by how hard the company's *name* is to link, and committed **before** any question exists.

    python -m evals.heldout_slots --variant A --write    # write template + pin (refuses to redo)
    python -m evals.heldout_slots --check                # is the committed assignment intact?

A row carries `company_slots`: for each company the question must mention, the ticker, the
stored name, the name class and the *style* the question must use to mention it (brand name,
legal name, ticker, informal). `question` is null until the question writer fills it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_PATH = HERE / "heldout_template.jsonl"
HASH_PATH = HERE / "heldout_template.sha256"
QUESTIONS_PATH = HERE / "heldout_questions.jsonl"
SEED = 20260930

MENTION_STYLES = ("brand", "legal", "ticker", "informal")
ENTITY_CLASSES = ("plain", "inverted_the", "punctuated", "share_class", "multi_word")

# tier -> (ANSWER, ANSWER_WITH_ASSUMPTION, ABSTAIN, company slots per row, cycled in row order).
# Rows within a tier are ordered ANSWER, ANSWER_WITH_ASSUMPTION, ABSTAIN.
TEMPLATES: dict[str, dict[str, tuple[int, int, int, list[int]]]] = {
    "A": {  # 50 questions: the dev set's behaviour mix (50 / 19 / 34 of 103) at half scale
        "lookup": (4, 2, 0, [1]),
        "aggregation": (5, 0, 0, [0, 0, 0, 0, 1]),
        "raw_facts": (3, 1, 0, [1]),
        "time": (3, 0, 2, [1, 1, 1, 1, 2]),
        "ratio": (3, 1, 0, [1, 1, 1, 2]),
        "unit_period": (1, 2, 1, [1]),
        "ambiguous": (0, 2, 2, [1, 1, 1, 0]),
        "out_of_scope": (0, 0, 4, [1, 1, 0, 0]),
        "adversarial": (1, 0, 4, [1, 1, 1, 0, 0]),
        "schema_bait": (0, 1, 3, [1]),
        "grounding": (2, 1, 0, [1, 1, 2]),
        "calibration_twin": (2, 0, 0, [1]),
    },
    "B": {  # 80 questions: enough scored cases to see a 5-case effect (see the protocol's power note)
        "lookup": (6, 3, 0, [1]),
        "aggregation": (8, 0, 0, [0, 0, 0, 0, 1]),
        "raw_facts": (5, 2, 0, [1]),
        "time": (5, 0, 3, [1, 1, 1, 1, 2]),
        "ratio": (5, 1, 0, [1, 1, 1, 2]),
        "unit_period": (2, 3, 1, [1]),
        "ambiguous": (0, 4, 3, [1, 1, 1, 0]),
        "out_of_scope": (0, 0, 6, [1, 1, 0, 0]),
        "adversarial": (2, 0, 6, [1, 1, 1, 0, 0]),
        "schema_bait": (0, 2, 4, [1]),
        "grounding": (3, 1, 1, [1, 1, 2]),
        "calibration_twin": (4, 0, 0, [1]),
    },
}
DEV_TIER_MIX = TEMPLATES["A"]  # the tiers of the 103-case dev set, each present

_LEGAL = re.compile(
    r"\b(Inc|Corp|Corporation|Co|Company|Ltd|plc|Holdings|Group|LLC|N\.V|S\.A)\b\.?", re.I
)


def template_rows(variant: str = "A") -> list[dict]:
    """The rows of a variant, without companies: id, tier, expected, slot count, no question."""
    rows = []
    for tier, (n_ans, n_asm, n_abs, slots) in TEMPLATES[variant].items():
        expected = ["ANSWER"] * n_ans + ["ANSWER_WITH_ASSUMPTION"] * n_asm + ["ABSTAIN"] * n_abs
        for i, exp in enumerate(expected):
            rows.append({"tier": tier, "expected": exp, "n_slots": slots[i % len(slots)]})
    for i, row in enumerate(rows, 1):
        row["id"] = f"H{i:02d}"
        row["question"] = None
        row["company_slots"] = []
    return [{k: r[k] for k in ("id", "tier", "expected", "n_slots", "question", "company_slots")}
            for r in rows]  # fmt: skip


def total_slots(variant: str = "A") -> int:
    return sum(r["n_slots"] for r in template_rows(variant))


def entity_class(name: str, ticker: str) -> str:
    """How the company's *stored name* is written, which is what linking has to survive."""
    if "(The)" in name:
        return "inverted_the"
    if "(Class" in name:
        return "share_class"
    core = _LEGAL.sub("", name).strip(" ,.")
    if re.search(r"[&\-'/\d]", core):
        return "punctuated"
    if len(core.split()) >= 2:
        return "multi_word"
    return "plain"


def assign(
    rows: list[dict],
    companies: list[tuple[int, str, str]],
    dev_tickers: set[str],
    seed: int = SEED,
) -> list[dict]:
    """Fill every row's `company_slots`: distinct companies, none from the dev set, drawn
    round-robin across name classes so the set is not dominated by plain names, each with a
    mention style drawn evenly. Deterministic for a seed."""
    rng = random.Random(seed)
    pools: dict[str, list[tuple[int, str, str]]] = {c: [] for c in ENTITY_CLASSES}
    for cik, ticker, name in sorted(companies):
        if ticker not in dev_tickers:
            pools[entity_class(name, ticker)].append((cik, ticker, name))
    for pool in pools.values():
        rng.shuffle(pool)
    need = sum(r["n_slots"] for r in rows)
    styles = [MENTION_STYLES[i % len(MENTION_STYLES)] for i in range(need)]
    rng.shuffle(styles)
    order = [c for c in ENTITY_CLASSES if pools[c]]
    out = copy.deepcopy(rows)
    rr = 0  # round-robin position over the name classes
    slot = 0  # index into the drawn mention styles
    for row in out:
        for _ in range(row["n_slots"]):
            for _ in range(len(order)):  # skip a class that has run dry
                cls = order[rr % len(order)]
                rr += 1
                if pools[cls]:
                    break
            else:
                raise ValueError("not enough eligible companies for the slots")
            cik, ticker, name = pools[cls].pop()
            row["company_slots"].append(
                {
                    "ticker": ticker,
                    "name": name,
                    "cik": cik,
                    "class": cls,
                    "mention_style": styles[slot],
                }
            )
            slot += 1
    return out


def dev_tickers(db_path: str, gold_path: Path = HERE / "gold.jsonl") -> set[str]:
    """Every company the 103 dev cases name, by gold SQL or by linking the question."""
    import duckdb

    from evals.entity_upper_bound import case_companies
    from ledgerql.entity_link import EntityLinker

    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        linker = EntityLinker.from_connection(con)
        found: set[str] = set()
        for line in gold_path.read_text().splitlines():
            case = json.loads(line)
            found |= {t for t, _ in case_companies(case.get("gold_sql"), con)}
            found |= {link.ticker for link in linker.link(case["question"])}
        return found
    finally:
        con.close()


def build_template(variant: str = "A", db_path: str = "data/ledgerql.duckdb", seed: int = SEED):
    import duckdb

    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        companies = con.execute("SELECT cik, ticker, name FROM companies").fetchall()
    finally:
        con.close()
    return assign(template_rows(variant), companies, dev_tickers(db_path), seed)


def assignment_digest(rows: list[dict]) -> str:
    """Hash of what must not change once fixed: which company sits where, in which style."""
    core = [[r["id"], r["tier"], r["expected"], r["company_slots"]] for r in rows]
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def load_template(path: Path = TEMPLATE_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def questions_written() -> bool:
    return QUESTIONS_PATH.exists()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variant", choices=sorted(TEMPLATES), default="A")
    ap.add_argument("--db", default="data/ledgerql.duckdb")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.check:
        ok = assignment_digest(load_template()) == HASH_PATH.read_text().split()[0]
        print("assignment intact" if ok else "ASSIGNMENT CHANGED")
        return 0 if ok else 1
    rows = build_template(args.variant, args.db, args.seed)
    if args.write:
        if HASH_PATH.exists():
            print("the assignment is already committed and pinned; refusing", file=sys.stderr)
            return 2
        TEMPLATE_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows))
        HASH_PATH.write_text(f"{assignment_digest(rows)}  heldout_template.jsonl (assignment)\n")
        print(f"wrote {TEMPLATE_PATH}: {len(rows)} rows, {total_slots(args.variant)} company slots")
        return 0
    from collections import Counter

    print(
        Counter(r["expected"] for r in rows),
        Counter(s["class"] for r in rows for s in r["company_slots"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
