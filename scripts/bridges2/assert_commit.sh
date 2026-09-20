#!/usr/bin/env bash
# Hard stop: the checkout must be EXACTLY the commit the figures will be
# attributed to, with no tracked file modified.
#
#   assert_commit.sh <full-40-char-commit> [repo-dir]
#
# Exits non-zero and prints the recovery command on any failure. Callers must
# let that exit code stop them (submit.sh and run_model_eval.sh both do): a
# check that only prints a mismatch fails exactly when a human is moving fast.
# Incident (2026-09-20): `git pull` aborted on a locally modified report, HEAD
# stayed on an old commit, the mismatch was printed, and sbatch ran anyway.
set -uo pipefail

expected="${1:-}"
repo="${2:-.}"

fail() {
    echo "ASSERT_COMMIT FAILED: $*" >&2
    exit 1
}

[ -n "$expected" ] || fail "usage: assert_commit.sh <full-40-char-commit> [repo-dir]"
[ "${#expected}" -eq 40 ] || fail "give the full 40-character commit hash (got ${#expected} chars): a prefix can match the wrong commit"
actual="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || fail "$repo is not a git checkout"

dirty="$(git -C "$repo" status --porcelain --untracked-files=no)"
if [ -n "$dirty" ]; then
    echo "ASSERT_COMMIT FAILED: tracked files are modified in $repo (this is what blocks git pull):" >&2
    echo "$dirty" >&2
    echo "Recover: cd $repo && git checkout -- reports/eval.md   (an old run regenerated it; safe to discard)" >&2
    echo "         then: git pull --ff-only origin main, and re-run." >&2
    echo "Anything OTHER than reports/eval.md modified: stop and look; do not discard it blindly." >&2
    exit 1
fi

if [ "$actual" != "$expected" ]; then
    echo "ASSERT_COMMIT FAILED: MISMATCH: checkout is at $actual, expected $expected" >&2
    echo "Recover: cd $repo && git checkout -- reports/eval.md  (if a pull was blocked by it)" >&2
    echo "         then: git pull --ff-only origin main, and re-run." >&2
    exit 1
fi

echo "commit verified: $actual"
