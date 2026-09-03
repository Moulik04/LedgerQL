import zipfile
from pathlib import Path

import duckdb

from ledgerql.data.ingest import IngestStats, ensure_staging_tables, ingest_quarter

# Real column order, confirmed against an actual SEC quarterly zip.
SUB_FIELDS = [
    "adsh",
    "cik",
    "name",
    "sic",
    "countryba",
    "stprba",
    "cityba",
    "zipba",
    "bas1",
    "bas2",
    "baph",
    "countryma",
    "stprma",
    "cityma",
    "zipma",
    "mas1",
    "mas2",
    "countryinc",
    "stprinc",
    "ein",
    "former",
    "changed",
    "afs",
    "wksi",
    "fye",
    "form",
    "period",
    "fy",
    "fp",
    "filed",
    "accepted",
    "prevrpt",
    "detail",
    "instance",
    "nciks",
    "aciks",
]
NUM_FIELDS = [
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
TAG_FIELDS = ["tag", "version", "custom", "abstract", "datatype", "iord", "crdr", "tlabel", "doc"]


def _row(fields: list[str], values: dict) -> str:
    """Builds one tab-delimited row, defaulting any unspecified field to ''."""
    return "\t".join(str(values.get(f, "")) for f in fields)


def make_fixture_zip(tmp_path: Path) -> Path:
    # Two filers: CIK 320193 (in the S&P 500 fixture set) and CIK 999999 (not).
    sub_rows = [
        _row(
            SUB_FIELDS,
            {
                "adsh": "0000320193-24-000123",
                "cik": "320193",
                "name": "APPLE INC",
                "sic": "3571",
                "form": "10-K",
                "period": "20240930",
                "fy": "2024",
                "fp": "FY",
                "filed": "20241101",
            },
        ),
        _row(
            SUB_FIELDS,
            {
                "adsh": "0000999999-24-000001",
                "cik": "999999",
                "name": "NOT S&P 500 CO",
                "sic": "9999",
                "form": "10-K",
                "period": "20240930",
                "fy": "2024",
                "fp": "FY",
                "filed": "20241101",
            },
        ),
    ]
    num_rows = [
        _row(
            NUM_FIELDS,
            {
                "adsh": "0000320193-24-000123",
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "version": "us-gaap/2024",
                "ddate": "20240930",
                "qtrs": "4",
                "uom": "USD",
                "value": "391035000000.0000",
            },
        ),
        _row(
            NUM_FIELDS,
            {
                "adsh": "0000320193-24-000123",
                "tag": "SomeDimensionalTag",
                "version": "us-gaap/2024",
                "ddate": "20240930",
                "qtrs": "4",
                "uom": "USD",
                "segments": "ProductLine=Foo",
                "value": "1000.0000",
            },
        ),
        _row(
            NUM_FIELDS,
            {
                "adsh": "0000999999-24-000001",
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "version": "us-gaap/2024",
                "ddate": "20240930",
                "qtrs": "4",
                "uom": "USD",
                "value": "5000000.0000",
            },
        ),
    ]
    tag_rows = [
        _row(
            TAG_FIELDS,
            {
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "version": "us-gaap/2024",
                "custom": "0",
                "abstract": "0",
                "datatype": "monetary",
                "iord": "D",
                "crdr": "C",
                "tlabel": "Revenue",
                "doc": "Revenue doc",
            },
        ),
    ]

    zip_path = tmp_path / "2024q4.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("sub.txt", "\t".join(SUB_FIELDS) + "\n" + "\n".join(sub_rows) + "\n")
        zf.writestr("num.txt", "\t".join(NUM_FIELDS) + "\n" + "\n".join(num_rows) + "\n")
        zf.writestr("tag.txt", "\t".join(TAG_FIELDS) + "\n" + "\n".join(tag_rows) + "\n")
    return zip_path


def test_ingest_quarter_filters_to_sp500_ciks(tmp_path):
    zip_path = make_fixture_zip(tmp_path)
    con = duckdb.connect(":memory:")
    ensure_staging_tables(con)

    stats = ingest_quarter(con, "2024q4", zip_path, ciks={320193})

    assert stats == IngestStats(
        quarter="2024q4", sub_rows=1, num_rows=2, tag_rows=1, null_value_rows=0, skipped_rows=0
    )

    sub_ciks = con.execute("SELECT cik FROM stg_sub").fetchall()
    assert sub_ciks == [(320193,)]

    # stg_num.agent_cik is the accession's SUBMITTER cik (parsed from the adsh
    # prefix), not necessarily the registrant's cik -- it happens to equal the
    # registrant cik (320193) in this fixture, but that's not guaranteed in
    # general (see stg_sub.cik for the real registrant cik).
    num_agent_ciks = con.execute("SELECT DISTINCT agent_cik FROM stg_num").fetchall()
    assert num_agent_ciks == [(320193,)]

    num_tags = con.execute("SELECT tag, segments FROM stg_num ORDER BY tag").fetchall()
    assert num_tags == [
        ("RevenueFromContractWithCustomerExcludingAssessedTax", ""),
        ("SomeDimensionalTag", "ProductLine=Foo"),
    ]


def test_ingest_quarter_is_idempotent_per_quarter(tmp_path):
    zip_path = make_fixture_zip(tmp_path)
    con = duckdb.connect(":memory:")
    ensure_staging_tables(con)

    ingest_quarter(con, "2024q4", zip_path, ciks={320193})
    ingest_quarter(con, "2024q4", zip_path, ciks={320193})

    sub_count = con.execute("SELECT COUNT(*) FROM stg_sub").fetchone()[0]
    assert sub_count == 1, "re-ingesting the same quarter must not duplicate stg_sub rows"

    num_count = con.execute("SELECT COUNT(*) FROM stg_num").fetchone()[0]
    assert num_count == 2, "re-ingesting the same quarter must not duplicate stg_num rows"

    tag_count = con.execute("SELECT COUNT(*) FROM stg_tag").fetchone()[0]
    assert tag_count == 1, "re-ingesting the same quarter must not duplicate stg_tag rows"
