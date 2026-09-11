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

Found via the real Phase 4 end-to-end run, not assumed: a real gold-set
query can pre-scale a value itself (`SELECT value / 1e9 AS
revenue_in_billions ...`), so the grounded row value is *already* in
billions (e.g. `391.035`). When the model then correctly restates that
same already-scaled number with a matching magnitude word ("$391.035
billion"), extract_numbers()'s own scaling multiplies it back up to
391035000000.0 for comparison -- which no longer matches the
already-scaled grounded value, and a genuinely correct answer gets
wrongly rejected. `_grounded_with_scales()` below widens the grounded
set to also include a value multiplied by a magnitude factor, but only
when that value's own column name names the scale (e.g.
`revenue_in_billions`, `revenue_millions` -- the real pattern the
model's own generated SQL uses), and only by that one matching factor.

An earlier version of this fix widened *every* grounded value by
*every* magnitude factor unconditionally, regardless of column name.
That accepted the pre-scaled cases it was meant to fix, but as a side
effect also silently disabled the magnitude/unit check for everything
else: any small number anywhere in a result would then also ground a
claim a thousand/million/billion/trillion times its size (e.g. a
`fiscal_year`-less count column `n=5` would ground "There were 5
billion"). Caught by a whole-branch review, not a real run -- see
`DECISIONS.md`'s 2026-09-11 entry on this bug. The column-name-scoped
version below is the fix; do not widen unconditionally again.
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


def _grounded_with_scales(columns: list[str], rows: list[tuple]) -> set[float]:
    scaled = {
        v for row in rows for v in row if isinstance(v, int | float) and not isinstance(v, bool)
    }
    for row in rows:
        for col, v in zip(columns, row, strict=True):
            if not isinstance(v, int | float) or isinstance(v, bool):
                continue
            col_lower = col.lower()
            for word, factor in _MAGNITUDE.items():
                if word in col_lower:
                    scaled.add(v * factor)
    return scaled


@dataclass
class VerifyResult:
    ok: bool
    ungrounded_numbers: list[float] = field(default_factory=list)
    detail: str | None = None


def verify(answer: str, columns: list[str], rows: list[tuple]) -> VerifyResult:
    grounded_values = _grounded_with_scales(columns, rows)
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
