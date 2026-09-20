import re
from pathlib import Path

import pytest

from tests.support import require_fixture


def test_a_missing_fixture_fails_loudly_and_names_the_path(tmp_path):
    with pytest.raises(pytest.fail.Exception) as excinfo:
        require_fixture(tmp_path / "absent.jsonl")
    message = str(excinfo.value)
    assert "absent.jsonl" in message
    assert "not skipped" in message  # says why this is a failure and not a skip


def test_an_existing_fixture_is_returned_unchanged(tmp_path):
    f = tmp_path / "there.jsonl"
    f.write_text("{}")
    assert require_fixture(f) == f


def test_the_hint_is_reported_alongside_the_path(tmp_path):
    with pytest.raises(pytest.fail.Exception) as excinfo:
        require_fixture(tmp_path / "x.duckdb", hint="build it with `make data`")
    assert "make data" in str(excinfo.value) and "x.duckdb" in str(excinfo.value)


def test_no_test_in_the_suite_may_skip():
    # A test that skips on a missing fixture reports green for a reason unrelated
    # to whether it passes. The Bridges-2 reports were the first instance (a fresh
    # clone silently skipped every "reproduces the report exactly" test); the
    # built DuckDB was the second. Guard the whole class: a missing fixture must
    # FAIL via tests.support.require_fixture. A skip that is genuinely about the
    # platform must say so on the same line with `# allow-skip: <reason>`.
    offenders = []
    for path in sorted(Path("tests").glob("test_*.py")):
        if path.name == "test_support.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"pytest\.skip\(|skipif\(|importorskip\(|mark\.skip\b", line):
                if "allow-skip:" not in line:
                    offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], f"silently-skipping tests: {offenders}"
