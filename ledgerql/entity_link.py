"""Company-name normalisation shared by entity linking and its offline upper bound.

Models write `name = 'Microsoft Corporation'` or `name = 'The Coca-Cola Company'`
because the question says so; the stored names are `Microsoft` and
`Coca-Cola Company (The)`, so an exact match returns nothing. The pieces here are
deterministic string handling only: no model, no network.
"""

from __future__ import annotations

import re

# Words that name a legal form, a share class or an article, not the company.
_STOP = frozenset(
    "the inc incorporated corp corporation co company ltd limited plc holdings holding group "
    "llc lp class a b c de sa nv ag and of com".split()
)


def name_tokens(name: str) -> frozenset[str]:
    """Lower-cased alphanumeric words of a company name, minus legal-form and article words."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    return frozenset(w for w in words if w not in _STOP)


def same_company(mention: str, stored_name: str) -> bool:
    """Do the two names refer to the same company? True when one name's distinctive words are
    contained in the other's (`Pfizer Inc.` / `Pfizer`, `The Coca-Cola Company` /
    `Coca-Cola Company (The)`, `Berkshire` / `Berkshire Hathaway`)."""
    a, b = name_tokens(mention), name_tokens(stored_name)
    return bool(a) and bool(b) and (a <= b or b <= a)


# --------------------------------------------------------------------------
# Linking a question's company mentions to the stored companies
# --------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402

# Brand names whose stored company name is different. Kept tiny and explicit.
ALIASES = {"google": "GOOGL", "facebook": "META"}

# Capitalised words that open a question, never a company.
_QUESTION_WORDS = frozenset(
    "what which who whom whose when where how why give show list compare among across "
    "did does do is are was were has have had can could will would from for with the and "
    "of in on by to at as per each every any all total combined most least highest lowest".split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9&.\-]*(?:'s)?")
_MIN_PREFIX = 4  # a mention shorter than this may only match a company name exactly
_MIN_TICKER = 3  # shorter tickers (A, F, ON, KO ...) collide with ordinary words


@dataclass(frozen=True)
class Link:
    mention: str  # the words of the question, as written
    ticker: str
    name: str  # the stored companies.name
    cik: int
    how: str  # "name", "ticker" or "alias"


def _squash(text: str) -> str:
    return "".join(sorted_tokens(text))


def sorted_tokens(text: str) -> list[str]:
    """Distinctive words in order (unlike `name_tokens`, which is a set), for concatenation."""
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return [w for w in words if w not in _STOP]


class EntityLinker:
    """Deterministic company linking: which stored companies does a question name?

    A question word run is matched against `companies.name` when its distinctive words,
    concatenated, equal the stored name's (`Exxon Mobil` / `ExxonMobil`, `The Coca-Cola
    Company` / `Coca-Cola Company (The)`), or begin it and begin no other company's
    (`JPMorgan` / `JPMorgan Chase`, `Meta` / `Meta Platforms`). An all-caps word of three
    letters or more that is a ticker links by ticker. Ambiguous mentions link to nothing.
    """

    def __init__(self, companies: list[tuple[int, str, str]]):
        self._companies = list(companies)
        self._by_ticker = {t: (cik, t, name) for cik, t, name in companies}
        self._squashed = [(_squash(name), (cik, t, name)) for cik, t, name in companies]

    @classmethod
    def from_connection(cls, con) -> EntityLinker:
        return cls(con.execute("SELECT cik, ticker, name FROM companies").fetchall())

    @classmethod
    def from_db(cls, db_path: str) -> EntityLinker:
        import duckdb

        con = duckdb.connect(db_path, read_only=True, config={"enable_external_access": "false"})
        try:
            return cls.from_connection(con)
        finally:
            con.close()

    def _match_name(self, squashed: str) -> tuple[int, str, str] | None:
        if not squashed:
            return None
        exact = [c for s, c in self._squashed if s == squashed]
        if len(exact) == 1:
            return exact[0]
        if exact or len(squashed) < _MIN_PREFIX:
            return None
        prefixed = [c for s, c in self._squashed if s.startswith(squashed)]
        return prefixed[0] if len(prefixed) == 1 else None

    def link(self, question: str) -> list[Link]:
        words = [(m.group(0), m.start()) for m in _WORD_RE.finditer(question)]
        clean = [w[:-2] if w.endswith("'s") else w for w, _ in words]
        # Maximal runs of capitalised words, so a company name is not split across a sentence.
        runs: list[list[int]] = []
        current: list[int] = []
        for i, w in enumerate(clean):
            if w[0].isupper() or w[0].isdigit():
                current.append(i)
            else:
                if current:
                    runs.append(current)
                current = []
        if current:
            runs.append(current)

        found: dict[str, Link] = {}
        for run in runs:
            i = 0
            while i < len(run):
                hit = None
                for j in range(len(run), i, -1):  # longest span first
                    span = [clean[k].rstrip(".") for k in run[i:j]]
                    text = " ".join(span)
                    if len(span) == 1 and span[0].lower() in _QUESTION_WORDS:
                        continue
                    hit = self._link_span(span, text)
                    if hit:
                        i = j - 1
                        break
                if hit and hit.ticker not in found:
                    found[hit.ticker] = hit
                i += 1
        return list(found.values())

    def _link_span(self, span: list[str], text: str) -> Link | None:
        if len(span) == 1:
            word = span[0]
            if word.isupper() and len(word) >= _MIN_TICKER and word in self._by_ticker:
                cik, t, name = self._by_ticker[word]
                return Link(text, t, name, cik, "ticker")
            alias = ALIASES.get(word.lower())
            if alias and alias in self._by_ticker:
                cik, t, name = self._by_ticker[alias]
                return Link(text, t, name, cik, "alias")
        match = self._match_name(_squash(text))
        if match:
            cik, t, name = match
            return Link(text, t, name, cik, "name")
        return None


_LINKERS: dict[str, EntityLinker] = {}


def linker_for(db_path: str | None = None) -> EntityLinker:
    """One linker per database, built on first use. Defaults to the pipeline's own database."""
    import os

    path = db_path or os.environ.get("LEDGERQL_DB_PATH", "data/ledgerql.duckdb")
    if path not in _LINKERS:
        _LINKERS[path] = EntityLinker.from_db(path)
    return _LINKERS[path]


def hint_for(question: str, linker: EntityLinker) -> str:
    """The text added to a generation prompt: each company the question names, resolved to
    the ticker and the exact stored name. Empty when the question names none."""
    links = linker.link(question)
    if not links:
        return ""
    lines = [
        "Companies named in the question, resolved against the database "
        "(names are stored with their own spelling, so filter on the ticker, or use the stored "
        "name exactly):"
    ]
    for link in links:
        lines.append(f"- \"{link.mention}\": ticker = '{link.ticker}', stored name '{link.name}'")
    return "\n".join(lines) + "\n\n"
