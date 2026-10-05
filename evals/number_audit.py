"""Independent audit of the numbers in a shipped answer (`evals/NUMBER_AUDIT_SPEC.md`).

Written from the spec, deliberately not from `ledgerql/verify.py`: it imports nothing from
`ledgerql/` (a test checks this), and it does not use `evals/year_audit.py`, which imports
`verify`. Its inputs are the answer text, the executed result, the executed SQL text and,
optionally, a read-only database for year and date labels. The SQL is read structurally (sqlglot)
for one thing only: which company its predicates name. Its string literals are read from the text.

    audit_answer(answer, columns, rows, sql=None, db_path=None) -> Audit
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache

import sqlglot
from sqlglot import exp

# ---------------------------------------------------------------------------------------------
# vocabulary

_SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_MAG_WORDS = {
    **_SCALE,
    "mil": 1e6,
    "mln": 1e6,
    "bil": 1e9,
    "tril": 1e12,
    "mn": 1e6,
    "mm": 1e6,
    "bn": 1e9,
    "tn": 1e12,
    "trn": 1e12,
}
_MAG_LETTERS = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}
_COLUMN_SCALE = (  # a column name that says what its numbers are in
    (re.compile(r"trillion|_tn\b|_trn\b", re.I), 1e12),
    (re.compile(r"billion|_bn\b|_b\b", re.I), 1e9),
    (re.compile(r"million|_mm\b|_mn\b|_m\b", re.I), 1e6),
    (re.compile(r"thousand|_k\b", re.I), 1e3),
)

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("January", "Jan"),
            ("February", "Feb"),
            ("March", "Mar"),
            ("April", "Apr"),
            ("May",),
            ("June", "Jun"),
            ("July", "Jul"),
            ("August", "Aug"),
            ("September", "Sept", "Sep"),
            ("October", "Oct"),
            ("November", "Nov"),
            ("December", "Dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

_FORM_CODES = ["10-K/A", "10-KT", "10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "11-K", "S-1",
               "S-3", "S-4", "F-1", "DEF 14A"]  # fmt: skip

_UNITS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split()
    )
}
_TENS = {
    w: 10 * i
    for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split())
    if w != "_"
}
_WORD = "|".join(sorted([*_UNITS, *_TENS, "hundred", *_SCALE], key=len, reverse=True))
_AFTER_SCALE = "(?:(?<=hundred)|(?<=thousand)|(?<=million)|(?<=billion)|(?<=trillion))"
_DIGIT_WORDS = "|".join(list(_UNITS)[:10])
_SPELLED = re.compile(
    rf"\b(?:a\s+(?=(?:hundred|thousand|million|billion|trillion)\b))?"
    rf"(?:{_WORD})(?:(?:[\s-]+|{_AFTER_SCALE}\s+and\s+)(?:{_WORD}))*"
    rf"(?:\s+point(?:\s+(?:{_DIGIT_WORDS}))+)?\b",
    re.I,
)

_DIGITS = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_NUMBER = re.compile(
    rf"(?<![\w.,])(?P<sign>[-−])?(?P<cur>(?:US)?[$€£]\s?)?(?P<num>{_DIGITS})(?P<exp>[eE][+-]?\d+)?"
    rf"(?:(?P<pct>\s?(?:%|percent\b|per\s?cent\b|percentage\s+points?\b|pp\b))"
    rf"|(?P<word>\s?(?:{'|'.join(sorted(_MAG_WORDS, key=len, reverse=True))})\b)"
    rf"|(?P<abbr>[kKmMbBtT])(?![A-Za-z0-9]))?"
)


_ISO = re.compile(r"(?<![\d-])((?:19|20)\d\d)-(\d{2})-(\d{2})(?![\d-])")
_MDY_NAMED = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:19|20)\d\d)(?!\d)")
_DMY_NAMED = re.compile(
    rf"(?<![\d.])(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH}),?\s+((?:19|20)\d\d)(?!\d)"
)
_US_NUMERIC = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})/((?:19|20)?\d\d)(?![\d/])")
_MONTH_YEAR = re.compile(rf"\b({_MONTH}),?\s+((?:19|20)\d\d)(?!\d)")
_MONTH_DAY = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?")
_PERIOD_LABEL = re.compile(r"\b([QH][1-4])\b")
_FY_LABEL = re.compile(r"\bFY\s?'?((?:19|20)?\d\d)(?!\d)")
_APOS_YEAR = re.compile(r"(?<![\w])['’](\d\d)(?!\d)")
_ORDINAL = re.compile(r"\b\d+(?:st|nd|rd|th)\b")
_LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_YEAR_SHAPE = re.compile(r"^(?:19|20)\d\d$")
# Spec section 2: only a hedged round number leaves its precision unstated.
_HEDGE = ("about", "approximately", "roughly", "around", "nearly")
_GLUED_ID = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]+\b")
# Spec 1.8: three or more groups of digits joined by hyphens (an accession number) are one claim.
_IDENTIFIER = re.compile(r"(?<![\w.,-])\d+(?:-\d+){2,}(?![\w-]|[.,]\d)")
_SQL_STRING = re.compile(r"'((?:[^']|'')*)'")


# ---------------------------------------------------------------------------------------------
# claims


@dataclass
class Claim:
    kind: str  # number | percent | year | date | period_label | identifier
    text: str
    value: float | None = None
    decimals: int = 0
    scale: float = 1.0
    percent: bool = False
    date: tuple[int | None, int | None, int | None] | None = None  # (year, month, day)
    hedged: bool = False  # "about", "roughly", "~" ... stands directly before the number
    status: str = "ungrounded"  # grounded | weak | derived | unresolved | ungrounded
    source: str = ""  # what grounded it

    @property
    def tolerance(self) -> float:
        """Half a unit of the last stated place, times the scale (spec section 2)."""
        return 0.5 * 10 ** (-self.decimals) * self.scale


@dataclass
class Audit:
    claims: list[Claim] = field(default_factory=list)

    def of(self, status: str) -> list[Claim]:
        return [c for c in self.claims if c.status == status]

    @property
    def ungrounded(self) -> list[Claim]:
        return self.of("ungrounded")

    @property
    def unresolved(self) -> list[Claim]:
        """Labels the auditor cannot tie to a company or rule out: neither clean nor invented."""
        return self.of("unresolved")

    @property
    def clean(self) -> bool:
        return not self.ungrounded


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


_MAGNITUDE_LIKE = re.compile(
    rf"\d+(?:{'|'.join([*_MAG_WORDS, *_MAG_LETTERS])})", re.I
)  # 391B, 5k, 12bn: a number with a scale attached, not an identifier


def _spelled_value(span: str) -> tuple[float, int, float] | None:
    """(value, decimals, precision scale) of a spelled-out number; None if it is a bare 'one' or not
    well formed. The precision unit is the scale word it ends on ("sixteen billion" is good to a
    billion), else 1."""
    words = [w for w in re.split(r"[\s-]+", span.lower()) if w and w != "and"]
    if words and words[0] == "a":
        words[0] = "one"
    frac: list[str] = []
    if "point" in words:
        i = words.index("point")
        words, frac = words[:i], words[i + 1 :]
    if words == ["one"]:
        return None
    total, current, last = 0, 0, ""  # last: tens | unit | hundred | scale
    for w in words:
        if w in _UNITS:
            if last in ("tens_unit", "unit", "tens") and not (last == "tens" and _UNITS[w] < 10):
                return None
            current += _UNITS[w]
            last = "tens_unit" if last == "tens" else "unit"
        elif w in _TENS:
            if last in ("tens", "tens_unit", "unit"):
                return None
            current += _TENS[w]
            last = "tens"
        elif w == "hundred":
            if last not in ("tens", "tens_unit", "unit") or current >= 10 * 10:
                return None
            current *= 100
            last = "hundred"
        else:  # a scale word
            if current == 0 and not total and last == "":
                return None
            total += max(current, 1) * int(_SCALE[w])
            current, last = 0, "scale"
    value = float(total + current)
    if frac:
        value += float("0." + "".join(str(_UNITS[w]) for w in frac))
    ends_on_scale = bool(words) and words[-1] in _SCALE and not frac
    return value, len(frac), float(_SCALE[words[-1]]) if ends_on_scale else 1.0


def _is_hedged(text: str, start: int) -> bool:
    """The number starting at `start` comes straight after a hedge word or a tilde."""
    before = text[:start].rstrip()
    if before.endswith("~"):
        return True
    last = re.search(r"[A-Za-z]+$", before)
    return bool(last) and last.group(0).lower() in _HEDGE


def _to_year(s: str) -> int:
    n = int(s)
    return n if n >= 100 else 2000 + n


def extract_claims(text: str, mask_strings: list[str] | None = None) -> list[Claim]:
    claims: list[Claim] = []
    masked: list[tuple[int, int]] = []

    def take(m: re.Match, claim: Claim | None) -> None:
        masked.append(m.span())
        if claim is not None:
            claims.append(claim)

    def free(m: re.Match) -> bool:
        return not any(a < m.end() and m.start() < b for a, b in masked)

    # Not claims: names and strings that hold a digit, form codes, ordinals, list markers.
    for name in sorted(set(mask_strings or ()), key=len, reverse=True):
        for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
            take(m, None)
    for code in _FORM_CODES:
        for m in re.finditer(rf"(?<![\w-]){re.escape(code)}(?![\w-])", text):
            if free(m):
                take(m, None)
    for pat in (_ORDINAL, _LIST_MARKER):
        for m in pat.finditer(text):
            if free(m):
                take(m, None)

    # Dates, longest forms first, so their parts are not read again as numbers.
    for pat, order in (
        (_ISO, "ymd"),
        (_MDY_NAMED, "Mdy"),
        (_DMY_NAMED, "dMy"),
        (_US_NUMERIC, "mdy"),
        (_MONTH_YEAR, "My"),
        (_MONTH_DAY, "Md"),
    ):
        for m in pat.finditer(text):
            if not free(m):
                continue
            parts = dict(zip(order, m.groups(), strict=True))
            month = _MONTHS.get(parts["M"].rstrip(".")) if "M" in parts else None
            if "m" in parts:
                month = int(parts["m"])
            year = _to_year(parts["y"]) if "y" in parts else None
            day = int(parts["d"]) if "d" in parts else None
            if (month is not None and not 1 <= month <= 12) or (
                day is not None and not 1 <= day <= 31
            ):
                continue
            take(m, Claim("date", m.group(0).strip(), date=(year, month, day)))

    # An identifier is one claim and none of its groups is a number or a year. A run in which every
    # group is a year is years, and is left for the number pass below.
    for m in _IDENTIFIER.finditer(text):
        if free(m) and not all(_YEAR_SHAPE.match(g) for g in m.group(0).split("-")):
            take(m, Claim("identifier", m.group(0)))

    for pat, build in (
        (_PERIOD_LABEL, lambda m: Claim("period_label", m.group(1))),
        (_FY_LABEL, lambda m: Claim("year", m.group(0), value=float(_to_year(m.group(1))))),
        (_APOS_YEAR, lambda m: Claim("year", m.group(0), value=float(_to_year(m.group(1))))),
    ):
        for m in pat.finditer(text):
            if free(m):
                take(m, build(m))

    # Identifiers with digits glued to letters (H2O, COVID19) are not claims; a number with a
    # scale attached (391B) is.
    for m in _GLUED_ID.finditer(text):
        if free(m) and not _MAGNITUDE_LIKE.fullmatch(m.group(0)):
            masked.append(m.span())

    for m in _NUMBER.finditer(text):
        if not free(m):
            continue
        suffix = m.group("pct") or m.group("word") or m.group("abbr")
        if not suffix and m.end() < len(text) and text[m.end()].isalpha():
            continue  # digits glued to letters: an identifier
        raw = m.group("num")
        value = float(raw.replace(",", ""))
        if m.group("exp"):
            value *= 10 ** int(m.group("exp")[1:])
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        scale = 1.0
        if m.group("word"):
            scale = _MAG_WORDS[m.group("word").strip().lower()]
        elif m.group("abbr"):
            scale = _MAG_LETTERS[m.group("abbr").lower()]
        plain = not (m.group("sign") or m.group("cur") or m.group("exp") or suffix or "," in raw)
        if plain and "." not in raw and _YEAR_SHAPE.match(raw):
            take(m, Claim("year", m.group(0).strip(), value=value))
            continue
        sign = -1.0 if m.group("sign") else 1.0
        percent = bool(m.group("pct"))
        take(
            m,
            Claim(
                "percent" if percent else "number",
                m.group(0).strip(),
                value=sign * value * scale,
                decimals=decimals,
                scale=scale,
                percent=percent,
                hedged=_is_hedged(text, m.start()),
            ),
        )

    work = _mask(text, masked)
    for m in _SPELLED.finditer(work):
        parsed = _spelled_value(m.group(0))
        if parsed is None:
            continue
        value, decimals, scale = parsed
        pct = re.match(r"\s*(percent\b|per\s?cent\b)", work[m.end() :], re.I)
        take(
            m,
            Claim(
                "percent" if pct else "number",
                m.group(0).strip(),
                value=value,
                decimals=decimals,
                scale=scale,
                percent=bool(pct),
                hedged=_is_hedged(work, m.start()),
            ),
        )
    return claims


# ---------------------------------------------------------------------------------------------
# evidence


def _is_number(v) -> bool:
    return isinstance(v, int | float | Decimal) and not isinstance(v, bool)


def _column_factor(name: str) -> float | None:
    for pat, factor in _COLUMN_SCALE:
        if pat.search(name or ""):
            return factor
    return None


@dataclass
class Evidence:
    cells: list[float]  # numbers the result states (and its row count)
    years: set[int]  # years in the result and in the executed SQL
    dates: set[dt.date]
    labels: set[str]
    operands: list[float] = field(default_factory=list)  # numeric cells only, for "derived"
    db_years: set[int] = field(default_factory=set)  # any company
    db_dates: set[dt.date] = field(default_factory=set)
    co_years: set[int] = field(default_factory=set)  # the companies the SQL names
    co_dates: set[dt.date] = field(default_factory=set)
    # the SQL restricts the company, and the auditor cannot tell to which
    company_unresolved: bool = False
    strings: list[str] = field(default_factory=list)  # the result's string cells
    sql_strings: list[str] = field(default_factory=list)  # the string literals of the SQL


def _without_identifiers(text: str) -> str:
    """`text` with every identifier blanked (spec 3.3, 3.4): in the evidence, as in an answer, an
    identifier is one string, and its groups state no number and no year. An ISO date and a run of
    years are not identifiers and are kept."""

    def blank(m: re.Match) -> str:
        run = m.group(0)
        if _ISO.fullmatch(run) or all(_YEAR_SHAPE.match(g) for g in run.split("-")):
            return run
        return " " * len(run)

    return _IDENTIFIER.sub(blank, text)


def build_evidence(columns, rows, sql, db=None, company=None, company_unresolved=False) -> Evidence:
    cells: list[float] = []
    operands: list[float] = []
    years: set[int] = set()
    dates: set[dt.date] = set()
    labels: set[str] = set()
    strings: list[str] = []
    for row in rows:
        for col, v in zip(columns, row, strict=False):
            if isinstance(v, dt.datetime):
                v = v.date()
            if isinstance(v, dt.date):
                dates.add(v)
                years.add(v.year)
            elif _is_number(v):
                f = float(v)
                cells.append(f)
                factor = _column_factor(col)
                if factor:
                    cells.append(f * factor)
                if f == int(f) and 1900 <= int(f) <= 2099:
                    years.add(int(f))
                else:
                    operands.append(f)
            elif isinstance(v, str):
                strings.append(v)
    cells.append(float(len(rows)))
    for t in [*strings, str(sql or "")]:
        for m in _ISO.finditer(t):
            dates.add(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        years.update(
            int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", _without_identifiers(t))
        )
        labels.update(_PERIOD_LABEL.findall(t))
    # numerals inside a string cell (spec 3.3); the SQL's numbers are not evidence
    for t in strings:
        for m in re.finditer(
            r"(?<![\d.])\d[\d,]*(?:\.\d+)?", _ISO.sub(" ", _without_identifiers(t))
        ):
            cells.append(float(m.group(0).replace(",", "")))
    ev = Evidence(cells, years, dates, labels, operands)
    ev.strings = strings
    ev.sql_strings = _SQL_STRING.findall(str(sql or ""))
    if db:
        ev.db_years, ev.db_dates = db
    if company:
        ev.co_years, ev.co_dates = company
    ev.company_unresolved = company_unresolved
    return ev


@lru_cache(maxsize=4)
def load_db_labels(db_path: str) -> tuple[frozenset[int], frozenset[dt.date], frozenset[str]]:
    """Years, dates and digit-bearing names the database holds, by plain read-only queries."""
    import duckdb

    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        dates = {
            d
            for sql in (
                "SELECT DISTINCT period_end_date FROM filings WHERE period_end_date IS NOT NULL",
                "SELECT DISTINCT ddate FROM financial_facts WHERE ddate IS NOT NULL",
            )
            for (d,) in con.execute(sql).fetchall()
        }
        years = {
            int(y)
            for (y,) in con.execute(
                "SELECT DISTINCT fiscal_year FROM filings WHERE fiscal_year IS NOT NULL"
            ).fetchall()
        } | {d.year for d in dates}
        names = {
            s
            for row in con.execute("SELECT name, ticker FROM companies").fetchall()
            for s in row
            if s and re.search(r"\d", s)
        }
        return frozenset(years), frozenset(dates), frozenset(names)
    finally:
        con.close()


# Which company the SQL names. A company predicate compares `cik`, `ticker` or `name` with a
# value. Comparing it with another column is a join key and a null test is an anti-join: neither
# restricts the query to a company, so a query with only those is cross-company.
_COMPANY_COLUMNS = {"cik", "ticker", "name"}
_WRAPPERS = (exp.Paren, exp.Cast, exp.TryCast, exp.Lower, exp.Upper, exp.Trim)


@dataclass(frozen=True)
class CompanyRefs:
    """What the SQL's company predicates say. `restricted`: there is at least one. `open`: at
    least one cannot be read as naming a company (a pattern, a range, a negation, a subquery that
    names none, SQL that does not parse)."""

    ciks: frozenset[int] = frozenset()  # numeric literals compared with cik
    names: frozenset[str] = frozenset()  # string literals compared with ticker or name, lowered
    restricted: bool = False
    open: bool = False


def _unwrap(node):
    while isinstance(node, _WRAPPERS):
        node = node.this
    return node


def _company_column(node) -> str | None:
    node = _unwrap(node)
    if isinstance(node, exp.Tuple):
        return next(filter(None, map(_company_column, node.expressions)), None)
    if isinstance(node, exp.Column) and node.name.lower() in _COMPANY_COLUMNS:
        return node.name.lower()
    return None


def _company_predicates(tree):
    """(predicate, column name, value side) for every comparison of a company column with
    something that is not a column. The value side is None unless the comparison is binary."""
    for p in tree.find_all(exp.Binary, exp.In, exp.Between):
        if not isinstance(p, exp.Predicate) or isinstance(p, exp.Is):
            continue
        if not isinstance(p, exp.Binary):
            if column := _company_column(p.this):
                yield p, column, None
            continue
        left, right = _company_column(p.this), _company_column(p.expression)
        if bool(left) == bool(right):
            continue  # no company column, or one on each side: a join key
        value = p.expression if left else p.this
        if not isinstance(_unwrap(value), exp.Column):  # against any other column: a join key
            yield p, left or right, value


def _negated(p) -> bool:
    if isinstance(p, exp.NEQ):
        return True
    while p := p.parent:
        if isinstance(p, exp.Not):
            return True
    return False


def company_refs(sql: str | None) -> CompanyRefs:
    if not (sql or "").strip():
        return CompanyRefs()
    try:
        trees = [t for t in sqlglot.parse(sql, read="duckdb") if t is not None]
    except sqlglot.errors.SqlglotError:
        return CompanyRefs(restricted=True, open=True)
    ciks: set[int] = set()
    names: set[str] = set()
    restricted = unreadable = False

    def literal(column: str, node) -> bool:
        node = _unwrap(node)
        if not isinstance(node, exp.Literal):
            return False
        text = str(node.this).strip()
        if column == "cik":
            if text.isdigit():
                ciks.add(int(text))
            return text.isdigit()
        if node.is_string and text:
            names.add(text.lower())
        return bool(node.is_string and text)

    for tree in trees:
        for p, column, value in _company_predicates(tree):
            restricted = True
            sub = p.args.get("query") if isinstance(p, exp.In) else _unwrap(value)
            if isinstance(sub, exp.Query):
                # a subquery names a company only through a company predicate of its own, and
                # those are read where they stand
                ok = any(True for _ in _company_predicates(sub)) and not _negated(p)
            elif _negated(p):
                ok = False
            elif isinstance(p, exp.EQ):
                ok = literal(column, value)
            elif isinstance(p, exp.Like | exp.ILike):  # without a wildcard, an equality
                v = _unwrap(value)
                ok = (
                    isinstance(v, exp.Literal)
                    and not re.search(r"[%_]", str(v.this))
                    and literal(column, v)
                )
            elif isinstance(p, exp.In) and isinstance(_unwrap(p.this), exp.Column):
                ok = bool(p.expressions) and all([literal(column, v) for v in p.expressions])
            else:
                ok = False
            unreadable = unreadable or not ok
    return CompanyRefs(frozenset(ciks), frozenset(names), restricted, unreadable)


@lru_cache(maxsize=4)
def load_companies(db_path: str) -> tuple[tuple[int, str, str], ...]:
    """(cik, ticker, name) of every company, ticker and name lowered."""
    import duckdb

    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        rows = con.execute("SELECT cik, ticker, name FROM companies").fetchall()
        return tuple(
            (int(c), (ticker or "").lower(), (name or "").lower()) for c, ticker, name in rows
        )
    finally:
        con.close()


def resolve_companies(db_path: str, refs: CompanyRefs) -> tuple[frozenset[int], bool]:
    """The ciks of the companies the SQL names, through the companies table, and whether every
    company predicate was resolved: each literal is a cik, a ticker or a name (case-insensitive)
    of a company in the table."""
    companies = load_companies(db_path)
    by_cik = {cik for cik, _, _ in companies}
    found = {cik for cik in refs.ciks if cik in by_cik}
    missing = len(found) < len(refs.ciks)
    for literal in refs.names:
        hits = {cik for cik, ticker, name in companies if literal in (ticker, name)}
        found |= hits
        missing = missing or not hits
    return frozenset(found), not (refs.open or missing)


@lru_cache(maxsize=64)
def load_company_labels(db_path: str, ciks: frozenset[int]) -> tuple[set[int], set[dt.date]]:
    """Fiscal years and period-end dates of the companies with these ciks. Empty if none."""
    if not ciks:
        return set(), set()
    import duckdb

    con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
    try:
        ciks = sorted(ciks)
        cm = ",".join("?" for _ in ciks)
        dates = {
            d
            for sql in (
                f"SELECT DISTINCT period_end_date FROM filings WHERE cik IN ({cm})"
                " AND period_end_date IS NOT NULL",
                f"SELECT DISTINCT ddate FROM financial_facts WHERE cik IN ({cm})"
                " AND ddate IS NOT NULL",
            )
            for (d,) in con.execute(sql, ciks).fetchall()
        }
        years = {
            int(y)
            for (y,) in con.execute(
                f"SELECT DISTINCT fiscal_year FROM filings WHERE cik IN ({cm})"
                " AND fiscal_year IS NOT NULL",
                ciks,
            ).fetchall()
        } | {d.year for d in dates}
        return years, dates
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------
# grounding


def _close(value: float, g: float, tol: float) -> bool:
    slack = tol + 1e-9 * max(abs(g), abs(value), 1.0)
    return abs(value - g) <= slack or abs(abs(value) - abs(g)) <= slack


def _grounded_by_cells(c: Claim, cells: list[float]) -> bool:
    for g in cells:
        if _close(c.value, g, c.tolerance) or (c.percent and _close(c.value, 100 * g, c.tolerance)):
            return True
    return False


def _coarse_tolerance(c: Claim) -> float | None:
    """For a hedged whole-number mantissa with trailing zeros ("about 420 billion", "roughly
    400,000"), the precision those zeros leave unstated: half a unit of the last non-zero place.
    None if there are none, or if the claim is not hedged: unhedged zeros are stated digits."""
    mantissa = abs(c.value) / c.scale
    if not c.hedged or c.decimals or mantissa < 10 or abs(mantissa - round(mantissa)) > 1e-9:
        return None
    digits = str(int(round(mantissa)))
    zeros = len(digits) - len(digits.rstrip("0"))
    return 0.5 * 10**zeros * c.scale if zeros else None


def _significant_digits(c: Claim) -> int:
    mantissa = abs(c.value) / c.scale
    digits = f"{mantissa:.{c.decimals}f}".replace(".", "").lstrip("0")
    # a written "750" states three digits; a spelled-out "a hundred" states one
    return len(digits.rstrip("0") if c.text[:1].isalpha() and not c.decimals else digits)


def _derived(c: Claim, operands: list[float]) -> bool:
    """Sum, difference, ratio or percentage change of two numeric result cells. Only for a claim
    that states at least three significant digits: with fewer, a coincidence is too likely."""
    if _significant_digits(c) < 3:
        return False
    uniq = sorted(set(operands))[:40]
    for a, b in itertools.permutations(uniq, 2):
        options = [a + b, a - b]
        if b:
            options += [a / b, 100 * a / b, 100 * (a - b) / b]
        if any(_close(c.value, x, c.tolerance) for x in options):
            return True
    return False


# A real label, but nothing ties it to this answer: another company's period on this company's
# figure is a misattributed period, so it is ungrounded (it was `weak` until 2026-10-03). The source
# text says why, so a reader can tell it from a label the database does not hold at all.
_OTHER_COMPANY = "the database holds this label, but not for the company the SQL names"
# The SQL restricts the company, the auditor cannot tell to which, and some company does have the
# label: it can neither be tied to this answer nor ruled out. Its own status, reported separately
# and never counted as ungrounded (the same principle as a timeout not scoring as wrong). With no
# company predicate at all the query is cross-company, and a single company's label is ungrounded.
_UNRESOLVED = (
    "the database holds this label, and the auditor cannot resolve which company the SQL names"
)


def ground(claim: Claim, ev: Evidence) -> Claim:
    def set_(status: str, source: str = "") -> Claim:
        claim.status, claim.source = status, source
        return claim

    def other_company() -> Claim:  # a label the database holds, but not for a company named
        if ev.company_unresolved:
            return set_("unresolved", _UNRESOLVED)
        return set_("ungrounded", _OTHER_COMPANY)

    if claim.kind == "period_label":
        return set_("grounded", "result/sql") if claim.text in ev.labels else set_("ungrounded")
    if claim.kind == "identifier":
        # The exact string, whole: not a piece of a longer run of digits and hyphens, and never
        # its groups as numbers (spec 3.8).
        whole = re.compile(rf"(?<![\d-]){re.escape(claim.text)}(?![\d-])")
        if any(whole.search(s) for s in ev.strings):
            return set_("grounded", "result")
        if any(whole.search(s) for s in ev.sql_strings):
            return set_("grounded", "sql literal")
        return set_("ungrounded")
    if claim.kind == "date":
        y, mo, d = claim.date

        def fits(x: dt.date) -> bool:
            return (
                (y is None or x.year == y)
                and (mo is None or x.month == mo)
                and (d is None or x.day == d)
            )

        if any(fits(x) for x in ev.dates):
            return set_("grounded", "result/sql")
        if any(fits(x) for x in ev.co_dates):
            return set_("grounded", "database, for the company the SQL names")
        if any(fits(x) for x in ev.db_dates):
            return other_company()
        return set_("ungrounded")
    if claim.kind == "year":
        if int(claim.value) in ev.years or _grounded_by_cells(claim, ev.cells):
            return set_("grounded", "result/sql")
        if int(claim.value) in ev.co_years:
            return set_("grounded", "database, for the company the SQL names")
        if int(claim.value) in ev.db_years:
            return other_company()
        return set_("ungrounded")
    if _grounded_by_cells(claim, ev.cells):
        return set_("grounded", "result")
    coarse = _coarse_tolerance(claim)
    if coarse is not None and any(
        _close(claim.value, g, coarse) or (claim.percent and _close(claim.value, 100 * g, coarse))
        for g in ev.cells
    ):
        return set_(
            "weak", "coarse rounding (a hedged round number, read to its last non-zero place)"
        )
    if _derived(claim, ev.operands):
        return set_("derived", "pair of result numbers")
    return set_("ungrounded")


def audit_answer(
    answer: str, columns, rows, sql: str | None = None, db_path: str | None = None
) -> Audit:
    rows = [tuple(r) for r in rows or []]
    masks = [v for r in rows for v in r if isinstance(v, str) and re.search(r"\d", v)]
    db = company = None
    unresolved = False
    if db_path:
        years, dates, db_names = load_db_labels(str(db_path))
        db = (set(years), set(dates))
        masks += list(db_names)
        refs = company_refs(sql)
        ciks, resolved = resolve_companies(str(db_path), refs)
        company = load_company_labels(str(db_path), ciks)
        unresolved = refs.restricted and not resolved
    ev = build_evidence(columns or [], rows, sql, db, company, unresolved)
    return Audit([ground(c, ev) for c in extract_claims(answer or "", masks)])
