# ruff: noqa: E501  (clause sentences are single literals so they read as the user sees them)
"""Stage 7a-bis: the framing that states what an answer assumed.

`write_answer` describes the table in front of it and, by design, never sees the question or the
SQL. So an answer to "What was Microsoft's net income in its most recent fiscal year?" states a
number and no period, or states one it made up. This builds the other half: the sentence(s) saying
which fiscal year was used, how a loose term was read, which company a brand name resolved to,
which years a sum covers, and so on.

**Deterministic by design.** The hard part is the period, and that is a lookup keyed by the SQL's
own filters, not language: no model is called here. The inputs are the question, the winning SQL and
the result's *shape* (`ResultShape`: column names and row count). **It never sees a value.** What it
may state beyond the question and the SQL are *labels* read from the database by a keyed lookup (a
fiscal year, the date a period ended, a unit string), never a financial figure, and the verifier is
told which years and day numbers those are (`Frame.years`, `Frame.numbers`) so grounding stays
meaningful. Every numeral here is therefore a year or a date label from the question, the SQL or
the database (`tests/test_frame.py` checks it, and that no result value leaks in).

A frame is `assumed` when it states something the question did not fix (a period resolved from "most
recent", a bare year read as a fiscal year, a metric chosen for "biggest", a term mapped to a concept,
an alias resolved, a sum over years). An assumed frame is what makes an answer `ANSWER_WITH_ASSUMPTION`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from ledgerql import meta_lookup

# The four concept views and the plain-English concept each stands for (docs/schema.md, "Concept views").
CONCEPT_VIEWS = {
    "v_revenue": "revenue",
    "v_net_income": "net income",
    "v_total_assets": "total assets",
    "v_cash": "cash",
}
_INSTANT_VIEWS = {"v_total_assets", "v_cash"}  # qtrs = 0: a balance at a date, not a flow
_METRIC_WORDS = {
    "v_revenue": r"revenue|sales",
    "v_net_income": r"net income|profit|earnings",
    "v_total_assets": r"assets",
    "v_cash": r"cash",
}
# A loose word and the concept view whose figure it is read as.
_TERMS = {"profit": ("net income", "v_net_income"), "earnings": ("net income", "v_net_income")}

_FISCAL_YEAR_Q = re.compile(r"(?:fiscal\s+(?:years?\s+)?|FY\s?)'?((?:19|20)\d\d)", re.I)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
_LATEST_Q = re.compile(r"\b(most recent|latest|last fiscal year|current fiscal year)\b", re.I)
_RANK_TERM = re.compile(r"\b(biggest|largest|top|best|highest)\b", re.I)
_SUM_Q = re.compile(
    r"\b(combined|summed|sum of|together|added up|every fiscal year|all fiscal years)\b", re.I
)
_COMPARE_Q = re.compile(r"\b(than|versus|vs\.?|compared|difference|larger|smaller|bigger)\b", re.I)
_UOM_Q = re.compile(r"\b(unit|uom)\b", re.I)
_TICKER_EQ = re.compile(r"ticker\s*=\s*'([A-Z0-9.\-]+)'")
_TICKER_IN = re.compile(r"ticker\s+IN\s*\(([^)]*)\)", re.I)


@dataclass(frozen=True)
class ResultShape:
    """What the framing may know about the result: its columns and how many rows. No values."""

    columns: list[str]
    row_count: int


@dataclass(frozen=True)
class Clause:
    kind: str
    text: str
    assumption: bool


@dataclass(frozen=True)
class Frame:
    clauses: tuple[Clause, ...] = ()
    years: frozenset[int] = frozenset()  # year labels the framing states (for the verifier)
    numbers: frozenset[int] = frozenset()  # day-of-month labels in the dates it states

    @property
    def text(self) -> str:
        return " ".join(c.text for c in self.clauses)

    @property
    def assumed(self) -> bool:
        return any(c.assumption for c in self.clauses)


# ----------------------------------------------------------------------------------------
# What the SQL does
# ----------------------------------------------------------------------------------------


@dataclass
class _Facts:
    views: list[str]
    uses_filings: bool
    fy_literals: list[int]
    latest: bool
    tickers: list[str]
    has_sum: bool
    scale: float | None
    selects_uom: bool
    ranks: bool
    projects_fiscal_year: bool


def _col(node, name: str) -> bool:
    return isinstance(node, exp.Column) and node.name.lower() == name


def _facts(sql: str) -> _Facts | None:
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001
        return None
    if tree is None:
        return None
    views: list[str] = []
    uses_filings = False
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name in CONCEPT_VIEWS and name not in views:
            views.append(name)
        uses_filings = uses_filings or name == "filings"
    fy: list[int] = []
    for node in tree.find_all(exp.EQ, exp.In):
        if _col(node.this, "fiscal_year"):
            values = node.expressions if isinstance(node, exp.In) else [node.args.get("expression")]
            for v in values:
                if isinstance(v, exp.Literal) and not v.is_string:
                    fy.append(int(float(v.this)))
    latest = any(_col(m.this, "fiscal_year") for m in tree.find_all(exp.Max))
    ranks = False
    top = tree.find(exp.Select)
    projections = list(top.expressions) if top is not None else []
    # Output names that are (an aggregate of) the `value` column: `MAX(value) AS max_value`.
    value_aliases = {
        p.alias.lower()
        for p in projections
        if p.alias and any(_col(c, "value") for c in p.find_all(exp.Column))
    }
    for order in tree.find_all(exp.Order):
        for key in order.expressions:
            inner = key.this if isinstance(key, exp.Ordered) else key
            desc = bool(isinstance(key, exp.Ordered) and key.args.get("desc"))
            if desc and _col(inner, "fiscal_year"):
                latest = True
            elif desc and isinstance(inner, exp.Column):
                ranks = (
                    ranks or inner.name.lower() == "value" or inner.name.lower() in value_aliases
                )
    tickers = list(_TICKER_EQ.findall(sql))
    for group in _TICKER_IN.findall(sql):
        tickers += re.findall(r"'([^']+)'", group)
    scale = None
    for div in tree.find_all(exp.Div):
        right = div.args.get("expression")
        if isinstance(right, exp.Literal) and not right.is_string:
            if float(right.this) in (1e9, 1e6):
                scale = float(right.this)
    return _Facts(
        views=views,
        uses_filings=uses_filings,
        fy_literals=sorted(set(fy)),
        latest=latest,
        tickers=list(dict.fromkeys(tickers)),
        has_sum=any(True for _ in tree.find_all(exp.Sum)),
        scale=scale,
        selects_uom=any(
            c.name.lower() == "uom" for p in projections for c in p.find_all(exp.Column)
        ),
        ranks=ranks,
        projects_fiscal_year=any(
            c.name.lower() == "fiscal_year" for p in projections for c in p.find_all(exp.Column)
        ),
    )


# ----------------------------------------------------------------------------------------
# Lookups (labels, never values)
# ----------------------------------------------------------------------------------------

_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]  # fmt: skip


def _date_text(d) -> tuple[str, int, int]:
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}", d.year, d.day


def _company(db_path, ticker: str) -> str | None:
    rows = meta_lookup.data(db_path, "SELECT name FROM companies WHERE ticker = ?", [ticker])
    return rows[0][0] if rows else None


def _period(db_path, view: str | None, ticker: str, fy: int | None):
    """(fiscal_year, period_end_date) of the latest (or the given) fiscal year for a company."""
    if view in CONCEPT_VIEWS:
        sql = f"SELECT fiscal_year, period_end_date FROM {view} WHERE ticker = ?"
        params: list = [ticker]
        if fy is not None:
            sql, params = sql + " AND fiscal_year = ?", params + [fy]
        rows = meta_lookup.data(db_path, sql + " ORDER BY fiscal_year DESC LIMIT 1", params)
    else:
        sql = (
            "SELECT f.fiscal_year, f.period_end_date FROM filings f JOIN companies c ON c.cik = f.cik "
            "WHERE c.ticker = ? AND f.form = '10-K'"
        )
        params = [ticker]
        if fy is not None:
            sql, params = sql + " AND f.fiscal_year = ?", params + [fy]
        rows = meta_lookup.data(db_path, sql + " ORDER BY f.fiscal_year DESC LIMIT 1", params)
    return rows[0] if rows else None


def _years_text(years: list[int]) -> str:
    years = [str(y) for y in years]
    return years[0] if len(years) == 1 else ", ".join(years[:-1]) + " and " + years[-1]


# ----------------------------------------------------------------------------------------
# The framing
# ----------------------------------------------------------------------------------------


def frame_answer(
    question: str,
    sql: str | None,
    result_shape: ResultShape,
    *,
    db_path: str | None = None,
    linker=None,
) -> Frame:
    """The sentences that state what answering this question assumed. Empty when nothing was."""
    facts = _facts(sql) if sql else None
    if facts is None:
        return Frame()
    if linker is None:
        try:
            from ledgerql.entity_link import linker_for

            linker = linker_for(db_path)
        except Exception:  # noqa: BLE001 - no database: no linking
            linker = None
    links = linker.link(question) if linker is not None else []
    view = facts.views[0] if facts.views else None
    explicit = [int(y) for y in _FISCAL_YEAR_Q.findall(question)]
    bare = [int(y) for y in _YEAR.findall(question)]
    asked_latest = bool(_LATEST_Q.search(question))
    clauses: list[Clause] = []
    numbers: set[int] = set()

    tickers = list(facts.tickers) or [link.ticker for link in links]
    names = {t: _company(db_path, t) for t in tickers}

    def dated(fy_end) -> str:
        fy, end = fy_end
        text, _, day = _date_text(end)
        numbers.add(day)
        return f"fiscal year {fy} (period ended {text})"

    # --- period -------------------------------------------------------------------------
    if facts.fy_literals:
        covered = explicit and set(facts.fy_literals) <= set(explicit)
        if not covered and len(facts.fy_literals) == 1 and bare and facts.fy_literals[0] in bare:
            n = facts.fy_literals[0]
            looked = _period(db_path, view, tickers[0], n) if len(tickers) == 1 else None
            ended = f", which ended on {_date_text(looked[1])[0]}" if looked else ""
            if looked:
                numbers.add(_date_text(looked[1])[2])
            clauses.append(Clause("period", f"{n} was read as fiscal year {n}{ended}.", True))
        elif not covered and not (bare and set(facts.fy_literals) <= set(bare)):
            clauses.append(
                Clause("period", f"Fiscal year {_years_text(facts.fy_literals)} was used.", True)
            )
    elif facts.latest and not facts.has_sum:
        lead = (
            "The most recent fiscal year on record"
            if asked_latest
            else "No fiscal year was specified, so the most recent one on record"
        )
        looked = {t: _period(db_path, view, t, None) for t in tickers}
        looked = {t: v for t, v in looked.items() if v}
        if looked and len(looked) == 1:
            ((_, v),) = looked.items()
            clauses.append(Clause("period", f"{lead}, {dated(v)}, was used.", True))
        elif looked:
            parts = "; ".join(f"{names.get(t) or t}, {dated(v)}" for t, v in looked.items())
            clauses.append(
                Clause(
                    "period",
                    f"The most recent fiscal year on record was used for each company: {parts}.",
                    True,
                )
            )
        elif not tickers and view:
            rows = meta_lookup.data(db_path, f"SELECT max(fiscal_year) FROM {view}")
            if rows and rows[0][0] is not None:
                clauses.append(
                    Clause(
                        "period",
                        f"The most recent fiscal year on record, fiscal year {rows[0][0]}, was used.",
                        True,
                    )
                )

    # --- how a brand name resolved --------------------------------------------------------
    for link in links:
        if link.how == "alias":
            clauses.append(
                Clause(
                    "entity",
                    f"'{link.mention}' was resolved to {link.name} (ticker {link.ticker}).",
                    True,
                )
            )

    # --- a loose term read as a concept ---------------------------------------------------
    for word, (concept, concept_view) in _TERMS.items():
        if (
            re.search(rf"\b{word}\b", question, re.I)
            and not re.search(r"\bnet\s+(income|profit|earnings)\b", question, re.I)
            and view == concept_view
        ):
            clauses.append(
                Clause("term", f"'{word.capitalize()}' was interpreted as {concept}.", True)
            )
            break

    # --- which metric a ranking used --------------------------------------------------------
    if facts.ranks and view and not tickers and not re.search(_METRIC_WORDS[view], question, re.I):
        term = _RANK_TERM.search(question)
        if term:
            clauses.append(
                Clause(
                    "metric",
                    f"'{term.group(1).capitalize()}' was measured by {CONCEPT_VIEWS[view]}.",
                    True,
                )
            )

    if facts.ranks and view and not tickers and not facts.fy_literals and not facts.latest:
        clauses.append(Clause("period", "All fiscal years on record were considered.", True))

    # --- a stated scale, and the raw unit ---------------------------------------------------
    if facts.scale is not None:
        word = "billions" if facts.scale == 1e9 else "millions"
        clauses.append(
            Clause(
                "unit",
                f"Figures are shown in {word}; the raw values are stored unscaled.",
                word not in question.lower(),
            )
        )
    if facts.selects_uom and _UOM_Q.search(question) and view:
        units = {
            r[0]
            for t in tickers
            for r in meta_lookup.data(
                db_path, f"SELECT DISTINCT uom FROM {view} WHERE ticker = ?", [t]
            )
        }
        if units == {"USD"}:
            clauses.append(
                Clause(
                    "unit",
                    "The raw values are stored in base USD, not thousands or millions.",
                    False,
                )
            )

    # --- a sum over years ---------------------------------------------------------------------
    if facts.has_sum and not facts.fy_literals and view and len(tickers) == 1:
        rows = meta_lookup.data(
            db_path, f"SELECT fiscal_year FROM {view} WHERE ticker = ? ORDER BY 1", [tickers[0]]
        )
        if rows:
            years = [r[0] for r in rows]
            clauses.append(
                Clause(
                    "sum",
                    f"It sums fiscal years {_years_text(years)}, all the fiscal years on record for {names.get(tickers[0]) or tickers[0]}.",
                    True,
                )
            )

    # --- a balance asked for across years -------------------------------------------------
    if (
        view in _INSTANT_VIEWS
        and len(facts.fy_literals) >= 2
        and _SUM_Q.search(question)
        and not facts.has_sum
    ):
        concept = CONCEPT_VIEWS[view].capitalize()
        clauses.append(
            Clause(
                "balance",
                f"{concept} is a point-in-time balance, so the figures for different years are not added together; each year is shown separately.",
                True,
            )
        )

    # --- two companies' fiscal years --------------------------------------------------------
    if len({t for t in tickers}) >= 2 and facts.latest and _COMPARE_Q.search(question):
        clauses.append(
            Clause(
                "fiscal_year_ends",
                "These fiscal years can cover different calendar periods, because the companies' fiscal years end at different times.",
                True,
            )
        )

    # A stored name that ends in a period ("Tesla, Inc.") must not double the sentence's own.
    clauses = [Clause(c.kind, re.sub(r"\.\.+$", ".", c.text), c.assumption) for c in clauses]
    text = " ".join(c.text for c in clauses)
    years = frozenset(int(y) for y in _YEAR.findall(text))
    return Frame(tuple(clauses), years, frozenset(numbers))
