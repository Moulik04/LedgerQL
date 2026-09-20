#!/usr/bin/env bash
# Pull, verify, and submit both Bridges-2 jobs -- or stop before sbatch.
#
#   scripts/bridges2/submit.sh <full-40-char-commit>
#
# Run on the cluster login node. Every step is a hard stop (set -e): nothing
# after a failed check can execute, so a mismatch cannot be printed and then
# ignored. Each job is pinned to the commit (EXPECTED_COMMIT) and re-verifies it
# before touching a GPU, so a hand-typed `sbatch` cannot skip this either.
#
# Overrides for testing: LEDGERQL_REPO (checkout), SBATCH (sbatch binary).
#
# The whole body sits in main() and the script exits before the closing brace
# is reached: `git pull` may rewrite THIS file, and bash reads a script
# incrementally, so an unwrapped body could execute a torn mixture of old and
# new lines.
set -euo pipefail

main() {
    local expected="${1:-}"
    local here repo sbatch_bin
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    repo="${LEDGERQL_REPO:-$HOME/ledgerql-bridges2/ledgerql}"
    sbatch_bin="${SBATCH:-sbatch}"

    if [ -z "$expected" ]; then
        echo "usage: submit.sh <full-40-char-commit>   (git rev-parse HEAD on the laptop)" >&2
        return 2
    fi
    if [ "${#expected}" -ne 40 ]; then
        echo "give the full 40-character commit hash (got ${#expected} chars)" >&2
        return 2
    fi

    cd "$repo"

    # 1. Tracked changes make `git pull` abort and leave HEAD on the old commit.
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "STOP: tracked files are modified, so git pull would abort:" >&2
        git status --porcelain --untracked-files=no >&2
        echo "Recover: git checkout -- reports/eval.md   (an old run regenerated it; safe to discard)" >&2
        echo "         then re-run this script. Anything else modified: stop and look." >&2
        return 1
    fi

    # 2. Pull. If it fails, stop -- do not fall through to the check and sbatch.
    if ! git pull --ff-only origin main; then
        echo "STOP: git pull failed. Recover: git checkout -- reports/eval.md, then git pull --ff-only origin main" >&2
        return 1
    fi

    # 3. The commit must be exactly the expected one.
    bash "$here/assert_commit.sh" "$expected" "$repo"

    # 4. Only now submit, each job pinned to the verified commit.
    "$sbatch_bin" --export=ALL,EXPECTED_COMMIT="$expected" "$repo/scripts/bridges2/run_qwen3_coder_30b_fp16.sbatch"
    "$sbatch_bin" --export=ALL,EXPECTED_COMMIT="$expected" "$repo/scripts/bridges2/run_qwen25_coder_32b_awq.sbatch"
}

main "$@"
exit $?
