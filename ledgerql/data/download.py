"""Caches SEC Financial Statement Data Sets quarterly zips locally.

SEC requires a descriptive User-Agent on requests to sec.gov — a generic
or missing one gets HTTP 403 (confirmed during Phase 1 design research).
"""

from pathlib import Path

import httpx

SEC_BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"
USER_AGENT = "LedgerQL (contact: moulikjain04@gmail.com)"

# Pinned as of 2026-09-02 to match the sanity-check figures in
# tests/test_data.py. Update deliberately (and re-verify the sanity
# figures) rather than recomputing "most recent" automatically.
QUARTERS = [
    "2024q3",
    "2024q4",
    "2025q1",
    "2025q2",
    "2025q3",
    "2025q4",
    "2026q1",
    "2026q2",
]


def download_quarter(quarter: str, cache_dir: Path, client: httpx.Client | None = None) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{quarter}.zip"
    if dest.exists():
        return dest

    owns_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60.0
    )

    temp_dest = dest.with_suffix(".zip.part")
    try:
        url = f"{SEC_BASE_URL}/{quarter}.zip"
        with client.stream("GET", url, headers={"User-Agent": USER_AGENT}) as response:
            response.raise_for_status()
            with temp_dest.open("wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        # Atomically rename temp file to final destination on success
        temp_dest.replace(dest)
    except Exception:
        # Clean up partial temp file on any error
        temp_dest.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            client.close()

    return dest


def download_all(
    quarters: list[str], cache_dir: Path, client: httpx.Client | None = None
) -> list[Path]:
    return [download_quarter(q, cache_dir, client=client) for q in quarters]
