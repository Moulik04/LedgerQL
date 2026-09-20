"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


def require_fixture(path: str | Path) -> Path:
    """Return `path`, or FAIL (never skip) if it is missing.

    A test that skips on a missing fixture reports green for a reason unrelated
    to whether the thing under test passes. The Bridges-2 per-case reports are
    the evidence behind every headline and every derived figure; they must be
    tracked in git (see .gitignore), and a checkout without them is broken, not
    "a checkout where this test does not apply".
    """
    path = Path(path)
    if not path.exists():
        pytest.fail(
            f"required fixture missing: {path} -- this is a failure, not skipped. "
            "Bridges-2 reports are evidence and must be tracked in git "
            "(`git ls-files reports/`); restore it, do not skip the test.",
            pytrace=False,
        )
    return path
