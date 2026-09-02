import httpx

from ledgerql.data.download import (
    QUARTERS,
    SEC_BASE_URL,
    USER_AGENT,
    download_all,
    download_quarter,
)


def test_quarters_list_has_eight_pinned_quarters():
    assert QUARTERS == [
        "2024q3",
        "2024q4",
        "2025q1",
        "2025q2",
        "2025q3",
        "2025q4",
        "2026q1",
        "2026q2",
    ]


def test_download_quarter_fetches_and_caches(tmp_path):
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        assert request.headers["user-agent"] == USER_AGENT
        return httpx.Response(200, content=b"fake-zip-bytes")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = download_quarter("2024q3", tmp_path, client=client)

    assert path == tmp_path / "2024q3.zip"
    assert path.read_bytes() == b"fake-zip-bytes"
    assert requested_urls == [f"{SEC_BASE_URL}/2024q3.zip"]


def test_download_quarter_skips_if_already_cached(tmp_path):
    cached = tmp_path / "2024q3.zip"
    cached.write_bytes(b"already-here")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make a network request when cached")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    path = download_quarter("2024q3", tmp_path, client=client)

    assert path == cached
    assert path.read_bytes() == b"already-here"


def test_download_all_fetches_every_quarter(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"x")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    paths = download_all(["2024q3", "2024q4"], tmp_path, client=client)

    assert paths == [tmp_path / "2024q3.zip", tmp_path / "2024q4.zip"]
    assert len(seen) == 2


def test_download_quarter_cleans_up_on_http_error(tmp_path):
    """Verify that failed downloads don't leave truncated files in the cache."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server-error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        download_quarter("2024q3", tmp_path, client=client)
        raise AssertionError("should have raised HTTPStatusError")
    except httpx.HTTPStatusError:
        pass

    # Verify no file was left behind
    dest = tmp_path / "2024q3.zip"
    assert not dest.exists(), "corrupt file should not be cached on HTTP error"
    # Also verify no temp file was left behind
    temp_dest = tmp_path / "2024q3.zip.part"
    assert not temp_dest.exists(), "temp file should be cleaned up on HTTP error"
