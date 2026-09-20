"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

BRIDGES2_HINT = (
    "Bridges-2 reports are evidence and must be tracked in git "
    "(`git ls-files reports/`); restore it."
)


def require_fixture(path: str | Path, hint: str = "") -> Path:
    """Return `path`, or FAIL (never skip) if it is missing.

    A test that skips on a missing fixture reports green for a reason unrelated
    to whether the thing under test passes. Two instances so far: the Bridges-2
    per-case reports (the evidence behind every headline and derived figure) and
    the built DuckDB the Phase 1 acceptance tests read. A checkout without a
    fixture is broken, not "a checkout where this test does not apply".
    """
    path = Path(path)
    if not path.exists():
        pytest.fail(
            f"required fixture missing: {path} -- this is a failure, not skipped. {hint}".rstrip(),
            pytrace=False,
        )
    return path
