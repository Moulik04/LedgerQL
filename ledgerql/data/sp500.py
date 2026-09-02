"""Loads the pinned S&P 500 constituent list (data/sp500_constituents.csv).

The CSV is a static snapshot, not fetched at runtime — see
scripts/fetch_sp500.py to regenerate it by hand.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sp500_constituents.csv"


@dataclass(frozen=True)
class SP500Company:
    ticker: str
    name: str
    cik: int
    gics_sector: str


def load_sp500(csv_path: Path = DEFAULT_CSV_PATH) -> list[SP500Company]:
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        return [
            SP500Company(
                ticker=row["ticker"],
                name=row["name"],
                cik=int(row["cik"]),
                gics_sector=row["gics_sector"],
            )
            for row in reader
        ]


def sp500_ciks(companies: list[SP500Company]) -> set[int]:
    return {c.cik for c in companies}
