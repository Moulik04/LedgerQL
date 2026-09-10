"""Stage 7b: numeric + fiscal-year verifier.

Checks every number the generated answer states is actually grounded in
the winning consensus result -- a claimed number with no matching value
anywhere in the result set forces an ABSTAIN (UNGROUNDED_ANSWER). A
wrong magnitude word ("million" instead of "billion") already fails the
general numeric check on its own, since extract_numbers() reconstructs
the claimed raw value using the stated magnitude before comparing it --
no separate unit-consistency mechanism is needed for that case.
Fiscal-year correctness needs a distinct, narrower check: years are
deliberately excluded from extract_numbers() (they appear constantly in
correct, grounded answers and are not the kind of "unsupported data
value" that check exists to catch), so a wrong fiscal year would
otherwise pass silently.
"""

import re
from dataclasses import dataclass, field

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# A bare 4-digit number that reads as a plausible fiscal/calendar year
# (2000-2099) is excluded -- these appear constantly in grounded,
# correct answers ("fiscal year 2024") and are not data values that
# need to trace back to the executed result set.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(-?\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")
# A bare number immediately followed by a hyphen and an uppercase letter
# is an SEC form code (e.g. "10-K", "10-Q"), not a data value.
_FORM_CODE_RE = re.compile(r"-[A-Z]")
# A standalone 4-digit year, not embedded in a larger number on either side.
_BARE_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        if _FORM_CODE_RE.match(text, match.end()):
            continue
        raw_digits, word = match.groups()
        # Strip a trailing sentence period (e.g. "fiscal year 2024.")
        # before the year-exclusion check and float conversion, so a
        # number followed immediately by a period is treated the same
        # as one that stands alone.
        digits = raw_digits.replace(",", "").rstrip(".")
        if not word and _YEAR_RE.match(digits):
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        if word and word.lower() in _MAGNITUDE:
            value *= _MAGNITUDE[word.lower()]
        numbers.append(value)
    return numbers


def extract_years(text: str) -> list[int]:
    return [int(m) for m in _BARE_YEAR_RE.findall(text)]


def _scalar_match(value: float, grounded: float, tolerance: float = 0.01) -> bool:
    return abs(value - grounded) <= max(abs(grounded) * tolerance, 1e-9)


@dataclass
class VerifyResult:
    ok: bool
    ungrounded_numbers: list[float] = field(default_factory=list)
    detail: str | None = None


def verify(answer: str, columns: list[str], rows: list[tuple]) -> VerifyResult:
    grounded_values = {v for row in rows for v in row if isinstance(v, int | float)}
    claimed = extract_numbers(answer)
    ungrounded = [n for n in claimed if not any(_scalar_match(n, g) for g in grounded_values)]

    if "fiscal_year" in columns:
        idx = columns.index("fiscal_year")
        grounded_years = {row[idx] for row in rows if row[idx] is not None}
        year_mismatches = [float(y) for y in extract_years(answer) if y not in grounded_years]
        ungrounded = ungrounded + year_mismatches

    if ungrounded:
        return VerifyResult(
            ok=False,
            ungrounded_numbers=ungrounded,
            detail=f"answer states unsupported number(s): {ungrounded}",
        )
    return VerifyResult(ok=True)
