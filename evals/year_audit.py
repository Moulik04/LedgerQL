"""Audit of what `ledgerql/verify.py` does not check: years in answer prose.

`verify.extract_numbers()` deliberately skips two classes of token: a bare
2000-2099 number with no magnitude word (a "year"), and a number immediately
followed by `-` and an uppercase letter (an SEC form code, "10-K"). Every other
integer, including small ones, must be grounded in the executed result. The
year check that replaces the first exclusion (`extract_years`) only runs when
the result has a `fiscal_year` column. So an answer whose result holds no
`fiscal_year` column can state any year and pass: U02's 30B prose said "fiscal
year 2022" over a bare value, and `hallucinated_numbers` was `[]`.

The answer writer sees only column names and rows, never the question
(`ledgerql/answer.py`), so a year in its prose that is not in the result was not
copied from anything it was shown. This scans every answered case for exactly
that: a bare year in the prose that appears in no result cell (an int, or a
string such as a date beginning with the year).

    python -m evals.year_audit reports/eval_bridges2_qwen3_30b_measured.jsonl
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from evals.passn_scoring import GOLD_PATH, load_jsonl
from evals.replay_repair_off import revert_exec_error_repairs
from ledgerql import verify

_YEAR_IN_TEXT = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def result_years(columns: list[str], rows: list) -> set[int]:
    """Every year the result contains: an integer-valued cell in 2000-2099, or a
    string cell (a date) containing a standalone 20xx."""
    years: set[int] = set()
    for row in rows:
        for cell in row:
            if isinstance(cell, bool):
                continue
            if isinstance(cell, int | float) and cell == int(cell) and 2000 <= int(cell) <= 2099:
                years.add(int(cell))
            elif isinstance(cell, str):
                years.update(int(y) for y in _YEAR_IN_TEXT.findall(cell))
    return years


def excluded_tokens(text: str) -> list[tuple[str, str]]:
    """The tokens `verify.extract_numbers` skips, as (kind, digits)."""
    found = []
    for match in verify._NUMBER_RE.finditer(text):
        raw, word = match.groups()
        digits = raw.replace(",", "").rstrip(".")
        if verify._FORM_CODE_RE.match(text, match.end()):
            found.append(("form_code", digits))
        elif not word and verify._YEAR_RE.match(digits):
            found.append(("year", digits))
    return found


def form_codes_ungrounded(answer: str, columns: list[str], rows: list) -> list[str]:
    """Form-code tokens ("10-K") that verify.py skips and the result does not contain."""
    text = " ".join(str(c) for row in rows for c in row if isinstance(c, str))
    codes = [d for kind, d in excluded_tokens(answer) if kind == "form_code"]
    return [d for d in codes if not re.search(rf"(?<!\d){re.escape(d)}-[A-Z]", text)]


def audit_record(record: dict, case: dict | None = None) -> dict:
    prose = verify.extract_years(record["answer"])
    grounded = result_years(record["columns"], record["rows"])
    ungrounded = [y for y in prose if y not in grounded]
    asked = {int(y) for y in _YEAR_IN_TEXT.findall(case["question"])} if case else set()
    return {
        "id": record["id"],
        "expected": record.get("expected"),
        "execution_correct": record.get("execution_correct"),
        "hallucinated_numbers": record.get("hallucinated_numbers"),
        "answer": record["answer"],
        "prose_years": prose,
        "ungrounded_years": ungrounded,
        # Only meaningful with the gold case: was the year one the question asked for?
        "year_status": (
            None
            if not ungrounded or case is None
            else "asked_for_but_ungrounded" if set(ungrounded) <= asked else "not_asked_for"
        ),
        "form_codes_ungrounded": form_codes_ungrounded(
            record["answer"], record["columns"], record["rows"]
        ),
        # verify.py compares prose years to the fiscal_year column, if there is one.
        "verifier_covers": "fiscal_year" in record["columns"],
    }


def audit(per_case: list[dict], cases_by_id: dict | None = None) -> dict:
    cases_by_id = cases_by_id or {}
    findings = [
        audit_record(r, cases_by_id.get(r["id"])) for r in per_case if r["answer"] is not None
    ]
    ungrounded = [f for f in findings if f["ungrounded_years"]]
    return {
        "answered": len(findings),
        "with_year_in_prose": sum(bool(f["prose_years"]) for f in findings),
        "ungrounded": ungrounded,
        "ungrounded_blind": [f for f in ungrounded if not f["verifier_covers"]],
        "ungrounded_correct": sum(f["execution_correct"] is True for f in ungrounded),
        "ungrounded_wrong": sum(f["execution_correct"] is not True for f in ungrounded),
        "not_asked_for": sum(f["year_status"] == "not_asked_for" for f in ungrounded),
        "form_codes_ungrounded": [f["id"] for f in findings if f["form_codes_ungrounded"]],
    }


def _print(label: str, per_case: list[dict], cases_by_id: dict) -> None:
    s = audit(per_case, cases_by_id)
    print(f"\n== {label}: {s['answered']} answered")
    print(f"  a bare year appears in the prose of {s['with_year_in_prose']}")
    print(f"  a prose year that is in no result cell: {len(s['ungrounded'])}")
    print(
        f"    of which verify.py cannot see (no fiscal_year column): {len(s['ungrounded_blind'])}"
    )
    print(f"    result correct: {s['ungrounded_correct']}, wrong: {s['ungrounded_wrong']}")
    print(f"    year the question never asked for: {s['not_asked_for']}")
    print(
        f"    ungrounded form codes (the other exclusion): {s['form_codes_ungrounded'] or 'none'}"
    )
    for f in s["ungrounded"]:
        years, status = f["ungrounded_years"], f["year_status"]
        print(f"    {f['id']:<4} {years} {status:<25} result_correct={f['execution_correct']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports", nargs="+", type=Path)
    args = ap.parse_args(argv)
    cases_by_id = {c["id"]: c for c in load_jsonl(GOLD_PATH)}
    for path in args.reports:
        per_case = load_jsonl(path)
        _print(f"{path.name} (as measured)", per_case, cases_by_id)
        shipped = revert_exec_error_repairs(per_case)
        _print(f"{path.name} (shipped: exec_error repair off)", shipped, cases_by_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
