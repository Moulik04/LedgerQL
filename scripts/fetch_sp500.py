"""One-time fetch: pull the current S&P 500 constituent list from Wikipedia
and write data/sp500_constituents.csv. Not run by `make data` — the CSV is
a pinned, committed snapshot. Re-run by hand and re-commit if the list
needs refreshing.
"""

import csv
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "LedgerQL research (contact: moulikjain04@gmail.com)"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "sp500_constituents.csv"


class _TableRowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._cur_row: list[str] | None = None
        self._in_cell = False
        self._cell_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cur_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            text = re.sub(r"\s+", " ", "".join(self._cell_text)).strip()
            # Strip stray Wikipedia footnote/reference markup (dagger/double-dagger
            # footnote markers, section/pilcrow marks) — narrowly targeted so it
            # can't accidentally strip a character from a legitimate company name.
            text = re.sub(r"[†‡§¶]", "", text).strip()
            self._cur_row.append(text)
            self._in_cell = False
        elif tag == "tr":
            if self._cur_row:
                self.rows.append(self._cur_row)
            self._cur_row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell_text.append(data)


def fetch_constituents_table_html() -> str:
    req = urllib.request.Request(WIKI_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    match = re.search(r'<table[^>]*id="constituents"[^>]*>(.*?)</table>', html, re.S)
    if not match:
        raise RuntimeError("Could not find the constituents table on the Wikipedia page")
    return match.group(1)


def parse_rows(table_html: str) -> list[tuple[str, str, int, str]]:
    parser = _TableRowParser()
    parser.feed(table_html)
    header, *data_rows = parser.rows
    idx = {name: i for i, name in enumerate(header)}
    rows = []
    for row in data_rows:
        ticker = row[idx["Symbol"]]
        name = row[idx["Security"]]
        sector = row[idx["GICS Sector"]]
        cik = int(row[idx["CIK"]])
        rows.append((ticker, name, cik, sector))
    return rows


def main() -> None:
    table_html = fetch_constituents_table_html()
    rows = parse_rows(table_html)
    if len(rows) < 490:
        raise RuntimeError(
            f"Expected ~500 S&P 500 rows, got {len(rows)} — page structure may have changed"
        )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "name", "cik", "gics_sector"])
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
