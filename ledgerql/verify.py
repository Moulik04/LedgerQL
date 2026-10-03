"""Stage 7b: numeric + fiscal-year verifier.

Checks every number the generated answer states is actually grounded in
the winning consensus result -- a claimed number with no matching value
anywhere in the result set forces an ABSTAIN (UNGROUNDED_ANSWER). A
wrong magnitude word ("million" instead of "billion") already fails the
general numeric check on its own, since extract_numbers() reconstructs
the claimed raw value using the stated magnitude before comparing it --
no separate unit-consistency mechanism is needed for that case.
Years need a distinct check: they are deliberately excluded from
extract_numbers() (they appear constantly in correct, grounded answers), so
without one a stated year would pass silently. With a `fiscal_year` column in
the result, a stated year must be one of that column's values. Without one, a
stated year must appear in a result cell (an integer, or a date string) or as a
year/date literal in the executed SQL, whose filter is what grounds the period.
The answer writer never sees the question, so a year in its prose that is in
neither was invented: the 30B stated "fiscal year 2022"/"2023" in 17 of 55
answers, over data that runs FY2024-2026, and the original column-only check
never looked because those results had no `fiscal_year` column (DECISIONS.md,
2026-09-29).

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

What counts as a stated number, and when it is grounded (rewritten 2026-10-03 after the independent
audit, `reports/number_audit_vs_verify.md`, found the verifier both too strict and too lenient on
planted values; the regression suite is `tests/planted_values.py`, shared with the auditor):

- A claim is digits (commas, decimals, an exponent, a sign, a currency symbol), optionally followed
  by `%`/`percent`/`percentage points` or a magnitude: `thousand`, `million`, `billion`, `trillion`,
  `mil`/`mln`/`bil`/`tril`, `bn`/`mn`/`mm`/`tn`/`trn`, or `k`/`m`/`b`/`t` attached to the number
  (`$416B`, `0.4T`). Or a spelled-out number (`forty-two`, `four hundred sixteen billion`, `two
  point five`, `a hundred`); a bare `one` is a pronoun, not a claim.
- **A stated figure must agree to the precision it states.** The place of its last stated digit
  sets the tolerance: it is correct for a result number if that number rounds to it there (within
  half a unit of the last place, times the scale). `416.2 billion` is correct for 416.161 billion,
  `416.3 billion` is not. There is no percentage slack. **Trailing zeros are stated digits unless
  the answer hedges the figure**: only directly after `about`, `approximately`, `roughly`, `around`,
  `nearly` or `~` is a whole number with trailing zeros also accepted as a rounding to its last
  non-zero place (and only when it states a magnitude or four or more digits and is at least 100).
  `about 420 billion` passes for 416.161 billion; `420 billion`, `about 450 billion` and `about 4
  billion` do not. Without the hedge, the trailing-zero reading would let through most of what the
  flat 1% tolerance did (amended 2026-10-03, DECISIONS.md).
- It is grounded by a number in the result (a column whose name names a scale grounds the cell times
  that scale, as before), by a context number the framing stated, by the number of rows (a plain
  count only, never a scaled figure or a percentage), and, for a percentage, by a ratio cell times
  100.
- Not claims: SEC form codes from a fixed list (`10-K`, `10-Q/A`, `8-K`, ...: a lookalike such as
  `391-K` is a number), digit ordinals (`3rd`), a list marker at the start of a line, digits glued
  to letters (`H2O`, `x86`), a string the result itself contains (`3M`, a company name).
- Fiscal-year labels `FY25` are years and are checked as years. `Q1`-`Q4` and `H1`/`H2` are labels
  that must appear in the result or the SQL.
- A date (`June 30, 2025`, `30 June 2025`, `2025-06-30`, `6/30/2025`, `June 30`) is one claim,
  grounded by the same month and day in a date in the result or a date literal in the SQL, or by a
  day the framing stated. The year inside a grounded date is not checked a second time.
"""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

_MAGNITUDE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}

# The extraction patterns as they were before 2026-10-03. Nothing below uses the first three any
# more; they stay because `evals/year_audit.py`, a diagnostic of that older behaviour, reads them.
_NUMBER_RE = re.compile(
    r"(?<![\d.])\$?(-?\d[\d,]*\.?\d*)\s*(trillion|billion|million|thousand|percent|%)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^20\d{2}$")
_FORM_CODE_RE = re.compile(r"-[A-Z]")
# A standalone 4-digit year, not embedded in a larger number on either side.
_BARE_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
# "FY25": a fiscal-year label with a two-digit year. ("FY2025" is already a bare year.)
_FY_SHORT_RE = re.compile(r"(?<![A-Za-z0-9])FY ?(\d{2})(?!\d)")

# --- what is masked before any number is read ---------------------------------------------------

# SEC form codes, a fixed list: anything else of that shape ("391-K") is a number and a letter.
_FORM_RE = re.compile(
    r"(?<![\w-])(?:10-K(?:/A|T)?|10-Q(?:/A)?|8-K(?:/A)?|20-F|40-F|6-K|11-K|S-[134]|F-1|DEF 14A)"
    r"(?![\w-])"
)
_FY_RE = re.compile(r"(?<![A-Za-z0-9])FY ?(?:\d{4}|\d{2})(?!\d)")
_ORDINAL_RE = re.compile(r"(?<![\w.])\d+(?:st|nd|rd|th)\b", re.IGNORECASE)
_LIST_MARKER_RE = re.compile(r"(?m)^[ \t]*\d{1,3}[.)](?=[ \t])")
_LABEL_RE = re.compile(r"(?<![A-Za-z0-9])(?:Q[1-4]|H[12])(?![A-Za-z0-9])")

_MONTH_NUMBER = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}
# Capitalised only, so the verb "may" is not a month.
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
)
_YEAR4 = r"(?:19|20)\d{2}"
_DATE_MDY_RE = re.compile(
    rf"(?<!\w)(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?!\d)"
    rf"(?:,?\s+(?P<year>{_YEAR4})(?!\d))?"
)
_DATE_DMY_RE = re.compile(
    rf"(?<![\w.])(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month>{_MONTH})(?!\w)"
    rf"(?:,?\s+(?P<year>{_YEAR4})(?!\d))?"
)
_DATE_ISO_RE = re.compile(r"(?<![\w-])(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?![\w-])")
_DATE_US_RE = re.compile(r"(?<![\w/])(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})(?![\w/])")
_ISO_IN_DATA_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

# --- numbers in digits --------------------------------------------------------------------------

# The power of ten each magnitude stands for. A single letter counts only when attached to the
# number and not followed by another letter or digit ("416B", "0.4T", never "4 bytes").
_SCALE_EXPONENT = {
    "thousand": 3, "k": 3,
    "million": 6, "mil": 6, "mln": 6, "mn": 6, "mm": 6, "m": 6,
    "billion": 9, "bil": 9, "bn": 9, "b": 9,
    "trillion": 12, "tril": 12, "tn": 12, "trn": 12, "t": 12,
}  # fmt: skip
_DIGITS_RE = re.compile(
    # not glued to a word ("H2O", "x86") or a decimal point; a hyphen after a word is not a minus
    r"(?<![\w.])(?P<sign>[-−]?)(?:US\$|[$€£])?"
    r"(?P<int>\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?P<frac>\.\d+)?(?P<exp>[eE][+-]?\d+(?![\w.]))?"
    r"(?:\s?(?P<pct>%|percent\b|per cent\b|percentage points?\b|pp\b)"
    r"|\s?(?P<word>thousand|million|billion|trillion|tril|trn|mil|mln|bil|bn|mn|mm|tn)\b"
    r"|(?P<abbr>[kmbt])(?![A-Za-z0-9]))?",
    re.IGNORECASE,
)

# The words that make a round number a rounding ("about 420 billion"): directly before the figure.
_HEDGE_RE = re.compile(
    r"(?:\b(?:about|approximately|roughly|around|nearly)\s+|~\s*)$", re.IGNORECASE
)

# --- numbers in words ---------------------------------------------------------------------------

_UNITS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_TENS = {
    w: (i + 2) * 10
    for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())
}
_WORD_SCALES = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}
_NUMBER_WORDS = set(_UNITS) | set(_TENS) | set(_WORD_SCALES) | {"hundred"}


@dataclass(frozen=True)
class Claim:
    """One thing the answer states that has to come from somewhere."""

    kind: str  # "number", "percent", "date" or "label"
    text: str
    start: int
    end: int
    value: float | None = None
    unit: float = 1.0  # the size of the last place the claim states
    coarse_unit: float | None = None  # the last non-zero place, for a hedged round number
    scaled: bool = False  # a magnitude was stated
    date: tuple[int | None, int, int] | None = None  # (year or None, month, day)


def _number_claim(
    kind: str,
    text: str,
    span: tuple[int, int],
    mantissa: Decimal,
    decimals: int,
    exponent: int,
    whole_digits: str,
    scaled: bool,
    hedged: bool,
) -> Claim:
    """`mantissa` is the number as written ("416.2"), `exponent` the power of ten of its magnitude.
    Decimal keeps "391.035 billion" exactly 391035000000. `hedged`: the answer says "about"."""
    unit = Decimal(10) ** (exponent - decimals)
    zeros = len(whole_digits) - len(whole_digits.rstrip("0"))
    coarse = None
    round_number = decimals == 0 and zeros and abs(mantissa) >= 100
    if hedged and round_number and (scaled or len(whole_digits) >= 4):
        coarse = float(unit * 10**zeros)
    value = float(mantissa * Decimal(10) ** exponent)
    return Claim(kind, text, span[0], span[1], value, float(unit), coarse, scaled)


def _hedged(text: str, start: int) -> bool:
    """The figure starting at `start` is directly preceded by a hedge word."""
    return bool(_HEDGE_RE.search(text, 0, start))


def _spelled_claims(text: str) -> list[Claim]:
    words = [(m.group().lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z]+", text)]

    def word(i: int) -> str | None:
        return words[i][0] if i < len(words) else None

    def joined(i: int) -> bool:
        """Word i follows word i-1 with only a space or a hyphen between them."""
        return 0 < i < len(words) and text[words[i - 1][2] : words[i][1]] in (" ", "-")

    def below_100(i: int) -> tuple[int, int] | None:
        w = word(i)
        if w in _TENS:
            if joined(i + 1) and 1 <= _UNITS.get(word(i + 1), 0) <= 9:
                return _TENS[w] + _UNITS[word(i + 1)], i + 2
            return _TENS[w], i + 1
        return (_UNITS[w], i + 1) if w in _UNITS else None

    def chunk(i: int) -> tuple[int, int] | None:
        """A number below 1000 starting at word i: (value, index after it)."""
        w = word(i)
        if joined(i + 1) and word(i + 1) == "hundred" and (w == "a" or 1 <= _UNITS.get(w, 0) <= 9):
            value, j = (1 if w == "a" else _UNITS[w]) * 100, i + 2
            k = j + 1 if joined(j) and word(j) == "and" else j
            rest = below_100(k) if joined(k) else None
            return (value + rest[0], rest[1]) if rest else (value, j)
        if w == "a" and joined(i + 1) and word(i + 1) in _WORD_SCALES:
            return 1, i + 1
        return below_100(i)

    def number(i: int) -> tuple[Claim, int] | None:
        first = chunk(i)
        if first is None:
            return None
        value, j = first
        decimals = ""
        if joined(j) and word(j) == "point":
            k = j + 1
            while joined(k) and 0 <= _UNITS.get(word(k), -1) <= 9:
                decimals += str(_UNITS[word(k)])
                k += 1
            if decimals:
                j = k
        exponent, scaled = 0, False
        if decimals:  # "two point five trillion"
            if joined(j) and word(j) in _WORD_SCALES:
                exponent, scaled, j = _WORD_SCALES[word(j)], True, j + 1
            mantissa, whole = Decimal(f"{value}.{decimals}"), str(value)
        else:
            total, ceiling = 0, 99
            while joined(j) and _WORD_SCALES.get(word(j), 99) < ceiling:
                ceiling = exponent = _WORD_SCALES[word(j)]
                total, value, scaled, j = total + value * 10**exponent, 0, True, j + 1
                following = chunk(j) if joined(j) else None
                if following is None:
                    break
                after = following[1]
                if joined(after) and _WORD_SCALES.get(word(after), 99) < ceiling:
                    value, j = following  # "... billion one hundred sixty-one million"
                    continue
                if ceiling == 3:  # "two thousand five hundred"
                    value, j, exponent = following[0], after, 0
                break
            total += value
            if total == 1 and j == i + 1 and word(i) == "one":
                return None  # a bare "one" is a pronoun
            mantissa, whole = Decimal(total) / 10**exponent, str(total // 10**exponent)
        kind = "number"
        if joined(j) and word(j) == "percent":
            kind, j = "percent", j + 1
        elif joined(j) and word(j) == "per" and joined(j + 1) and word(j + 1) == "cent":
            kind, j = "percent", j + 2
        span = (words[i][1], words[j - 1][2])
        claim = _number_claim(
            kind,
            text[span[0] : span[1]],
            span,
            mantissa,
            len(decimals),
            exponent,
            whole,
            scaled,
            _hedged(text, span[0]),
        )
        return claim, j

    claims, i = [], 0
    while i < len(words):
        found = number(i)
        if found:
            claims.append(found[0])
            i = found[1]
        else:
            i += 1
    return claims


def _digit_claims(text: str) -> list[Claim]:
    claims = []
    for m in _DIGITS_RE.finditer(text):
        whole = m["int"].replace(",", "")
        suffix = m["word"] or m["abbr"]
        plain = not (m["sign"] or m["frac"] or m["exp"] or m["pct"] or suffix)
        if plain and "," not in m["int"] and _YEAR_RE.match(whole):
            continue  # a bare year: checked as a year, not as a quantity
        sign = "-" if m["sign"] else ""
        frac = m["frac"] or ""
        exponent = (_SCALE_EXPONENT[suffix.lower()] if suffix else 0) + int((m["exp"] or "e0")[1:])
        claims.append(
            _number_claim(
                "percent" if m["pct"] else "number",
                m.group(),
                m.span(),
                Decimal(sign + whole + frac),
                max(len(frac) - 1, 0),
                exponent,
                whole,
                bool(suffix),
                _hedged(text, m.start()),
            )
        )
    return claims


def _date_claim(m: re.Match) -> Claim | None:
    month = m["month"]
    month = int(month) if month.isdigit() else _MONTH_NUMBER[month[:3].lower()]
    day = int(m["day"])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = int(m["year"]) if m["year"] else None
    return Claim("date", m.group(), m.start(), m.end(), date=(year, month, day))


def extract_claims(text: str, known_strings: list[str] | tuple[str, ...] = ()) -> list[Claim]:
    """Every number, percentage, date and period label the text states, in order. Bare years are
    not here (`extract_years`). `known_strings` are strings the result itself holds (a company
    name such as "3M"): where the text repeats one, its digits and number words are not claims."""
    claims: list[Claim] = []

    def blank(start: int, end: int) -> None:
        nonlocal text
        text = text[:start] + " " * (end - start) + text[end:]

    for m in _FORM_RE.finditer(text):
        blank(*m.span())
    for regex in (_DATE_MDY_RE, _DATE_DMY_RE, _DATE_ISO_RE, _DATE_US_RE):
        for m in regex.finditer(text):
            claim = _date_claim(m)
            if claim:
                claims.append(claim)
                blank(*m.span())
    for m in _LABEL_RE.finditer(text):
        claims.append(Claim("label", m.group(), m.start(), m.end()))
        blank(*m.span())
    for regex in (_FY_RE, _ORDINAL_RE, _LIST_MARKER_RE):
        for m in regex.finditer(text):
            blank(*m.span())
    for known in sorted(set(known_strings), key=len, reverse=True):
        # a name, repeated as a whole word: never a digit run inside a longer number
        if re.search(r"[A-Za-z]", known):
            for m in re.finditer(rf"(?<!\w){re.escape(known)}(?!\w)", text):
                blank(*m.span())
    claims += _spelled_claims(text) + _digit_claims(text)
    return sorted(claims, key=lambda c: c.start)


def extract_numbers(text: str) -> list[float]:
    return [c.value for c in extract_claims(text) if c.kind in ("number", "percent")]


def _year_positions(text: str) -> list[tuple[int, int]]:
    found = [(m.start(1), int(m.group(1))) for m in _BARE_YEAR_RE.finditer(text)]
    found += [(m.start(1), 2000 + int(m.group(1))) for m in _FY_SHORT_RE.finditer(text)]
    return sorted(found)


def extract_years(text: str) -> list[int]:
    return [year for _, year in _year_positions(text)]


def result_years(rows: list[tuple]) -> set[int]:
    """Years present in a result: an integer-valued cell in 2000-2099, or a string
    cell (a date) containing a standalone 20xx."""
    years: set[int] = set()
    for row in rows:
        for cell in row:
            if isinstance(cell, bool):
                continue
            if isinstance(cell, int | float) and cell == int(cell) and 2000 <= int(cell) <= 2099:
                years.add(int(cell))
            elif isinstance(cell, dt.date):
                years.add(cell.year)
            elif isinstance(cell, str):
                years.update(extract_years(cell))
    return years


def sql_years(sql: str | None) -> set[int]:
    """Standalone 20xx years in the executed SQL: `fiscal_year = 2025`,
    `'2024-09-28'`. A digit run inside a longer number is not a year."""
    return set(extract_years(sql)) if sql else set()


def _dates_in(value: object) -> set[tuple[int, int, int]]:
    """The dates a result cell or the SQL text holds."""
    if isinstance(value, dt.date):
        return {(value.year, value.month, value.day)}
    if isinstance(value, str):
        return {(int(y), int(m), int(d)) for y, m, d in _ISO_IN_DATA_RE.findall(value)}
    return set()


def _number(value: object) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return float(value) if isinstance(value, Decimal) else None


def _states(claim: Claim, grounded: float) -> bool:
    """The claim is a correct statement of `grounded` at the precision the claim states."""
    gap = abs(claim.value - grounded)
    return any(
        unit is not None and gap <= unit / 2 * (1 + 1e-9)
        for unit in (claim.unit, claim.coarse_unit)
    )


def _grounded_with_scales(columns: list[str], rows: list[tuple]) -> set[float]:
    scaled = {v for row in rows for v in map(_number, row) if v is not None}
    for row in rows:
        for col, cell in zip(columns, row, strict=True):
            v = _number(cell)
            if v is None:
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
    # the text of every claim that was not grounded: numbers and years as written, dates, labels
    ungrounded_claims: list[str] = field(default_factory=list)


def verify(
    answer: str,
    columns: list[str],
    rows: list[tuple],
    sql: str | None = None,
    context_years: set[int] | frozenset[int] | None = None,
    context_numbers: set[int] | frozenset[int] | None = None,
) -> VerifyResult:
    """`context_years` and `context_numbers` are the year and day-of-month labels the framing
    (`ledgerql/frame.py`) says it stated, read from the database by a keyed lookup. They ground
    exactly those labels and nothing else: a year or day the framing did not name still fails."""
    context_days = set(context_numbers or ())
    grounded_values = _grounded_with_scales(columns, rows) | {float(n) for n in context_days}
    cells = [cell for row in rows for cell in row]
    # a ratio cell (0.172) may be stated as a percentage (17.2%); nothing else is scaled by 100
    percent_values = grounded_values | {v * 100 for v in map(_number, cells) if v is not None}
    strings = [cell for cell in cells if isinstance(cell, str)]
    dates = set().union(*(_dates_in(cell) for cell in cells), _dates_in(sql))
    labelled = " ".join([*strings, sql or ""])
    known = [
        s for s in strings
        if re.search(r"\d", s) or _NUMBER_WORDS & set(re.findall(r"[a-z]+", s.lower()))
    ]  # fmt: skip

    ungrounded: list[float] = []
    other: list[str] = []  # dates and labels: claims with no number to report
    texts: list[str] = []
    dated: list[tuple[int, int]] = []  # spans of dates the result grounds, year included
    for claim in extract_claims(answer, known):
        if claim.kind == "date":
            year, month, day = claim.date
            if any(m == month and d == day and year in (None, y) for y, m, d in dates):
                if year is not None:
                    dated.append((claim.start, claim.end))
            elif day not in context_days:
                other.append(claim.text)
        elif claim.kind == "label":
            if not re.search(
                rf"(?<![A-Za-z0-9]){claim.text}(?![A-Za-z0-9])", labelled, re.IGNORECASE
            ):
                other.append(claim.text)
        else:
            pool = percent_values if claim.kind == "percent" else grounded_values
            # the number of rows grounds a plain count ("the ten companies"), never a scaled figure
            counted = claim.kind == "number" and not claim.scaled and claim.unit == 1
            if any(_states(claim, g) for g in pool) or (counted and claim.value == len(rows)):
                continue
            ungrounded.append(claim.value)
            texts.append(claim.text)

    if "fiscal_year" in columns:
        idx = columns.index("fiscal_year")
        grounded_years = {row[idx] for row in rows if row[idx] is not None} | set(
            context_years or ()
        )
    else:
        grounded_years = result_years(rows) | sql_years(sql) | set(context_years or ())
    for at, year in _year_positions(answer):
        if year not in grounded_years and not any(s <= at < e for s, e in dated):
            ungrounded.append(float(year))
            texts.append(str(year))

    if ungrounded or other:
        return VerifyResult(
            ok=False,
            ungrounded_numbers=ungrounded,
            detail=f"answer states unsupported number(s): {ungrounded + other}",
            ungrounded_claims=texts + other,
        )
    return VerifyResult(ok=True)
