"""Deterministic explanations for abstains.

When the pipeline abstains it used to return only a reason code, so the user was never told *why*.
This returns a sentence, and it is deliberately **not** generated: one template per reason code
(`TEMPLATES`), filled only from the question and the entity linker's resolution of it (company,
fiscal period), plus a registry of documented data gaps (`known_gaps.json`) that takes over when a
question matches one. No model is called anywhere in this path, and no template can emit a number
that is not in the question or the linker's output (`tests/test_refusal.py` checks both).

A known gap is a fact from `docs/schema.md` (banks with no standard revenue tag, no segment or
geographic breakdowns, annual figures only, staging tables not queryable, canonical tickers for
dual-class shares), each with the quotation that anchors it, and a trigger. Triggers that depend
on the data ("no revenue rows for this company", "no 8-K filings for this company") are decided
by the database, never assumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ledgerql import meta_lookup

REASON_CODES = (
    "OUT_OF_SCOPE",
    "SCHEMA_MISMATCH",
    "AMBIGUOUS",
    "NO_DATA",
    "COST_LIMIT",
    "LOW_AGREEMENT",
    "UNGROUNDED_ANSWER",
    "EXEC_ERROR",
)

# The generic sentence per reason code. {company} and {period} come only from the question and
# the entity linker; NO_DATA and AMBIGUOUS choose among variants by what the question supplied.
TEMPLATES: dict[str, str] = {
    "OUT_OF_SCOPE": (
        "This question is outside what this database can answer: it holds figures reported in "
        "the 10-K filings of S&P 500 companies."
    ),
    "SCHEMA_MISMATCH": (
        "This database has no table or column that holds the requested information."
    ),
    "AMBIGUOUS": "The question can be read more than one way. {ask}",
    "NO_DATA": "{no_data}",
    "COST_LIMIT": (
        "The query this question needs was too expensive to run safely, so it was not run."
    ),
    "LOW_AGREEMENT": (
        "The system could not settle on a single answer to this question with enough confidence, "
        "so it did not give one."
    ),
    "UNGROUNDED_ANSWER": (
        "A draft answer could not be checked against the query result (a figure or period in it "
        "did not match), so it was withheld."
    ),
    "EXEC_ERROR": "The query for this question could not be run against the database.",
}

GAPS_PATH = Path(__file__).resolve().parent / "known_gaps.json"
_DUAL_CLASS = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA"}  # docs/schema.md, dual-class note
_PERIOD = re.compile(r"(?:fiscal\s+(?:year\s+)?|FY\s?)'?((?:19|20)\d\d)", re.I)
_BARE_YEAR = re.compile(r"\b((?:19|20)\d\d)\b")


@dataclass(frozen=True)
class Refusal:
    text: str
    gap: str | None  # the documented gap that explains it, if one does
    code: str


def load_gaps(path: Path = GAPS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text())


def extract_period(question: str) -> str | None:
    """The fiscal year the question names, in its own digits."""
    m = _PERIOD.search(question)
    if m:
        return f"fiscal year {m.group(1)}"
    m = _BARE_YEAR.search(question)
    return m.group(1) if m else None


def _links(question: str, db_path: str | None):
    try:
        from ledgerql.entity_link import linker_for

        return linker_for(db_path).link(question)
    except Exception:  # noqa: BLE001 - no database or linker: fall back to the generic text
        return []


def _data(db_path: str | None, sql: str, params: list) -> list[tuple]:
    return meta_lookup.data(db_path, sql, params)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _gap_text(gap: dict, question: str, links: list, db_path: str | None) -> str | None:
    """The gap's sentence if its data condition holds, else None."""
    condition = gap["condition"]
    fields: dict[str, str] = {}
    if condition is None:
        return gap["text"]
    if condition == "dual_class":
        m = re.search(gap["pattern"], question)
        mention = m.group(0)
        fields = {"canonical": _DUAL_CLASS[mention], "mention": mention}
    elif condition in ("no_revenue_rows", "no_8k_rows"):
        for link in links:
            if condition == "no_revenue_rows":
                missing = (
                    _data(db_path, "SELECT 1 FROM v_revenue WHERE cik = ? LIMIT 1", [link.cik])
                    == []
                )
                known = _data(
                    db_path, "SELECT 1 FROM v_net_income WHERE cik = ? LIMIT 1", [link.cik]
                )
                ok = missing and bool(
                    known
                )  # the company exists in the data but has no revenue tag
            else:
                forms = _data(
                    db_path,
                    "SELECT DISTINCT form FROM filings WHERE cik = ? ORDER BY 1",
                    [link.cik],
                )
                names = [f[0] for f in forms]
                ok = bool(names) and "8-K" not in names
                if ok:
                    fields["forms"] = _join([n for n in names if n in ("10-K", "10-Q")] or names)
            if ok:
                fields["company"] = link.name
                return gap["text"].format(**fields)
        return None
    return gap["text"].format(**fields)


def explain(
    reason_code: str,
    question: str,
    *,
    db_path: str | None = None,
    guardrail_events=(),
) -> Refusal:
    """The sentence that tells the user why this question was not answered."""
    if reason_code not in TEMPLATES:
        raise ValueError(f"unknown reason code {reason_code!r}; expected one of {REASON_CODES}")
    links = _links(question, db_path)
    for gap in load_gaps():
        if re.search(gap["pattern"], question, re.I if gap["id"] != "dual_class_ticker" else 0):
            text = _gap_text(gap, question, links, db_path)
            if text is not None:
                return Refusal(text, gap["id"], reason_code)
    period = extract_period(question)
    company = _join([link.name for link in links]) if links else None
    if reason_code == "NO_DATA":
        if company and period:
            no_data = f"No 10-K in this database covers {company} for {period}."
        elif company:
            no_data = f"No 10-K in this database has the requested figure for {company}."
        else:
            no_data = "No data in this database matches this question."
        return Refusal(no_data, None, reason_code)
    if reason_code == "AMBIGUOUS":
        ask = (
            "Please say which company, metric or period you mean."
            if period
            else "Please say which fiscal year you mean."
        )
        return Refusal(TEMPLATES["AMBIGUOUS"].format(ask=ask), None, reason_code)
    return Refusal(TEMPLATES[reason_code], None, reason_code)
