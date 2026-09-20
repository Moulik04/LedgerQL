#!/usr/bin/env bash
# Run on your LAPTOP, from the repo root. Sends the WORKING TREE's source to
# Bridges-2, because the cluster's checkout is stale (it clones from GitHub;
# local main has commits origin lacks, and Phase 5.5 work is uncommitted) and
# the job runs whatever is in ~/ledgerql-bridges2/ledgerql.
#
# One password prompt: SSH connection sharing carries all three steps. Verifies
# by checksum that the cluster now holds byte-identical source.
#
#   scripts/bridges2/sync_code.sh            # send + verify
#   scripts/bridges2/sync_code.sh --dry-run  # list what would be sent; no ssh
set -euo pipefail

REMOTE_DIR='$HOME/ledgerql-bridges2/ledgerql'
PATHS=(ledgerql evals scripts docs/schema.md pyproject.toml uv.lock Makefile)
# macOS tar otherwise adds AppleDouble ._* files.
export COPYFILE_DISABLE=1
TAR_ARGS=(--exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store')

if [ ! -f evals/run_eval.py ]; then
    echo "Run from the repo root." >&2
    exit 1
fi

if [ "${1:-}" = "--dry-run" ]; then
    tar "${TAR_ARGS[@]}" -czf - "${PATHS[@]}" | tar -tzf - | grep -v '/$' | sort
    exit 0
fi

CP="$HOME/.ssh/cm-bridges2-%C"
SSH=(ssh -o ControlMaster=auto -o ControlPath="$CP" -o ControlPersist=15m bridges2)

echo "1/3 sending source (one password prompt)..."
tar "${TAR_ARGS[@]}" -czf - "${PATHS[@]}" \
    | "${SSH[@]}" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR && echo sent"

echo "2/3 checksumming on the cluster..."
FILES="$(tar "${TAR_ARGS[@]}" -czf - "${PATHS[@]}" | tar -tzf - | grep -v '/$' | sort)"
LOCAL_SUMS="$(echo "$FILES" | while read -r f; do shasum -a 256 "$f"; done)"
REMOTE_SUMS="$("${SSH[@]}" "cd $REMOTE_DIR && sha256sum \$(cat)" <<<"$FILES")"

echo "3/3 comparing..."
if diff <(echo "$LOCAL_SUMS") <(echo "$REMOTE_SUMS") >/dev/null; then
    echo "OK: $(echo "$FILES" | wc -l | tr -d ' ') files identical on the cluster."
else
    echo "MISMATCH between laptop and cluster:" >&2
    diff <(echo "$LOCAL_SUMS") <(echo "$REMOTE_SUMS") >&2 || true
    exit 1
fi
"${SSH[@]}" -O exit 2>/dev/null || true
