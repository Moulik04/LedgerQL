"""Parses SEC quarterly zips into staging tables, filtered to a set of CIKs.

Staging tables mirror sub.txt/num.txt/tag.txt column-for-column (minus the
few SUB columns we never use) so a data-quality question can always be
traced back to exactly what SEC published, before any transform runs.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb

SUB_COLUMNS = ["adsh", "cik", "name", "sic", "form", "period", "fy", "fp", "filed"]
NUM_COLUMNS = [
    "adsh",
    "tag",
    "version",
    "ddate",
    "qtrs",
    "uom",
    "segments",
    "coreg",
    "value",
    "footnote",
]
TAG_COLUMNS = ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr", "tlabel", "doc"]


@dataclass(frozen=True)
class IngestStats:
    quarter: str
    sub_rows: int
    num_rows: int
    tag_rows: int
    skipped_rows: int


def ensure_staging_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS stg_sub (
            adsh VARCHAR, cik INTEGER, name VARCHAR, sic VARCHAR,
            form VARCHAR, period VARCHAR, fy VARCHAR, fp VARCHAR, filed VARCHAR,
            quarter VARCHAR
        )
    """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS stg_num (
            adsh VARCHAR, tag VARCHAR, version VARCHAR, ddate VARCHAR, qtrs INTEGER,
            uom VARCHAR, segments VARCHAR, coreg VARCHAR, value DOUBLE, footnote VARCHAR,
            cik INTEGER, quarter VARCHAR
        )
    """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS stg_tag (
            tag VARCHAR, version VARCHAR, custom VARCHAR, abstract VARCHAR,
            datatype VARCHAR, iord VARCHAR, crdr VARCHAR, tlabel VARCHAR, doc VARCHAR,
            quarter VARCHAR
        )
    """
    )


def _read_tsv_rows(zf: zipfile.ZipFile, filename: str) -> csv.DictReader:
    raw = zf.read(filename).decode("utf-8")
    return csv.DictReader(io.StringIO(raw), delimiter="\t")


def ingest_quarter(
    con: duckdb.DuckDBPyConnection, quarter: str, zip_path: Path, ciks: set[int]
) -> IngestStats:
    con.execute("DELETE FROM stg_sub WHERE quarter = ?", [quarter])
    con.execute("DELETE FROM stg_num WHERE quarter = ?", [quarter])
    con.execute("DELETE FROM stg_tag WHERE quarter = ?", [quarter])

    skipped = 0
    with zipfile.ZipFile(zip_path) as zf:
        sub_by_adsh_in_scope: set[str] = set()
        sub_rows = []
        for row in _read_tsv_rows(zf, "sub.txt"):
            try:
                cik = int(row["cik"])
            except (KeyError, ValueError):
                skipped += 1
                continue
            if cik not in ciks:
                continue
            sub_by_adsh_in_scope.add(row["adsh"])
            sub_rows.append(
                [
                    row.get("adsh", ""),
                    cik,
                    row.get("name", ""),
                    row.get("sic", ""),
                    row.get("form", ""),
                    row.get("period", ""),
                    row.get("fy", ""),
                    row.get("fp", ""),
                    row.get("filed", ""),
                    quarter,
                ]
            )

        num_rows = []
        for row in _read_tsv_rows(zf, "num.txt"):
            if row.get("adsh") not in sub_by_adsh_in_scope:
                continue
            try:
                cik = int(row["adsh"].split("-")[0])
            except (IndexError, ValueError):
                skipped += 1
                continue
            try:
                qtrs = int(row["qtrs"])
                value = float(row["value"])
            except (KeyError, ValueError):
                skipped += 1
                continue
            num_rows.append(
                [row.get(c, "") for c in NUM_COLUMNS[:4]]
                + [qtrs]
                + [row.get("uom", ""), row.get("segments", ""), row.get("coreg", "")]
                + [value, row.get("footnote", "")]
                + [cik, quarter]
            )

        tag_rows = [
            [row.get(c, "") for c in TAG_COLUMNS] + [quarter]
            for row in _read_tsv_rows(zf, "tag.txt")
        ]

    if sub_rows:
        con.executemany(
            f"INSERT INTO stg_sub VALUES ({', '.join('?' * (len(SUB_COLUMNS) + 1))})", sub_rows
        )
    if num_rows:
        con.executemany(
            f"INSERT INTO stg_num VALUES ({', '.join('?' * (len(NUM_COLUMNS) + 2))})", num_rows
        )
    if tag_rows:
        con.executemany(
            f"INSERT INTO stg_tag VALUES ({', '.join('?' * (len(TAG_COLUMNS) + 1))})", tag_rows
        )

    return IngestStats(
        quarter=quarter,
        sub_rows=len(sub_rows),
        num_rows=len(num_rows),
        tag_rows=len(tag_rows),
        skipped_rows=skipped,
    )


def ingest_all(
    con: duckdb.DuckDBPyConnection, quarter_zips: list[tuple[str, Path]], ciks: set[int]
) -> list[IngestStats]:
    ensure_staging_tables(con)
    return [ingest_quarter(con, quarter, zip_path, ciks) for quarter, zip_path in quarter_zips]
