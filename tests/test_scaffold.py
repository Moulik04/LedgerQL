"""Phase 0 smoke test: the package imports and the version is set.

Real coverage starts in Phase 1 (tests/test_data.py) and grows with each
subsequent phase per LEDGERQL_MASTER_PROMPT.md.
"""

import ledgerql


def test_version_is_set():
    assert ledgerql.__version__
