#!/bin/bash
# Job body for the Phase 5 model comparison. Invoked by one of the
# run_*.sbatch wrappers inside an active SLURM allocation with real
# GPU(s) -- do not run this directly on a login node (no GPU there).
#
# Usage: run_model_eval.sh <hf-repo-id> <tensor-parallel-size>
#   e.g. run_model_eval.sh Qwen/Qwen2.5-Coder-32B-Instruct-AWQ 1
#        run_model_eval.sh Qwen/Qwen3-Coder-30B-A3B-Instruct 2
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <hf-repo-id> <tensor-parallel-size>" >&2
    exit 1
fi
REPO_ID="$1"
TP_SIZE="$2"
# Sanitize both ":" and "/" (HF repo ids contain "/") for filesystem/scp safety.
SANITIZED_MODEL="$(echo "$REPO_ID" | tr ':/' '-')"

ROOT="$HOME/ledgerql-bridges2"
VLLM_PYTHON="$ROOT/vllm-env/.venv/bin"

if [ -z "${LOCAL:-}" ]; then
    echo "\$LOCAL is not set -- this must run inside a real SLURM GPU allocation, not a login node." >&2
    exit 1
fi

cd "$ROOT/ledgerql"

if [ ! -f data/ledgerql.duckdb ]; then
    echo "data/ledgerql.duckdb not found -- copy it over first (see docs/bridges2.md)." >&2
    exit 1
fi

# Model weights (~20-80GB) are downloaded fresh into this job's node-local
# scratch, not pre-staged on $HOME -- $HOME/jet has a hard 25GiB project
# quota (confirmed real, too small for these checkpoints), while $LOCAL is
# node-local NVMe scratch (confirmed real: 28T on a real H100 node),
# outside that quota entirely, and wiped after the job -- fine since each
# model is only run once. HF_HOME redirects huggingface_hub's (and so
# vLLM's) cache there instead of the default ~/.cache/huggingface.
export HF_HOME="$LOCAL/hf_cache"
mkdir -p "$HF_HOME"

echo "Starting vllm serve for $REPO_ID (tensor-parallel-size=$TP_SIZE)..."
echo "First run downloads the checkpoint into \$LOCAL ($LOCAL) -- this can take a while on top of model-load time."
"$VLLM_PYTHON/vllm" serve "$REPO_ID" \
    --port 8000 \
    --tensor-parallel-size "$TP_SIZE" \
    > vllm_server.out 2> vllm_server.err &
VLLM_PID=$!
trap 'kill "$VLLM_PID" 2>/dev/null || true' EXIT

echo "Waiting for vllm to be ready (checkpoint download + load can take well over 10 minutes)..."
for i in $(seq 1 360); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "vllm is ready."
        break
    fi
    if [ "$i" -eq 360 ]; then
        echo "vllm did not become ready after 360 attempts (30 min) -- aborting." >&2
        echo "--- vllm_server.err (tail) ---" >&2
        tail -n 50 vllm_server.err >&2 || true
        exit 1
    fi
    sleep 5
done

echo "Confirming GPU(s) are actually being used (not silently falling back to CPU)..."
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv

echo "Running eval with LLM_BACKEND=vllm OLLAMA_MODEL=$REPO_ID ..."
LLM_BACKEND=vllm OLLAMA_MODEL="$REPO_ID" uv run python evals/run_eval.py --db data/ledgerql.duckdb

DATE_STAMP="$(date +%Y-%m-%d)"
cp reports/eval.md "reports/eval_bridges2_${SANITIZED_MODEL}.md"
cp "reports/eval_${DATE_STAMP}.jsonl" "reports/eval_bridges2_${SANITIZED_MODEL}_${DATE_STAMP}.jsonl"

echo ""
echo "Done. Results at:"
echo "  $ROOT/ledgerql/reports/eval_bridges2_${SANITIZED_MODEL}.md"
echo "  $ROOT/ledgerql/reports/eval_bridges2_${SANITIZED_MODEL}_${DATE_STAMP}.jsonl"
