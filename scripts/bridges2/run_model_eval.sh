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

# HARD STOP, before any module load or GPU work: the job runs only on the exact
# commit its figures will be attributed to. EXPECTED_COMMIT is mandatory, so a
# hand-typed `sbatch` that skips scripts/bridges2/submit.sh cannot skip this.
# (Incident 2026-09-20: a pull aborted, HEAD stayed on an old commit, the
# mismatch was printed, and both jobs ran the wrong code anyway.)
: "${EXPECTED_COMMIT:?EXPECTED_COMMIT is required -- submit with scripts/bridges2/submit.sh <full-commit-hash>}"
bash "$ROOT/ledgerql/scripts/bridges2/assert_commit.sh" "$EXPECTED_COMMIT" "$ROOT/ledgerql"

# A real smoke test found vLLM's flashinfer sampler JIT-compiles a CUDA
# kernel at model-load time and fails ("CUDA compiler and CUDA toolkit
# headers are incompatible") against the default cuda/12.6.1 module --
# cuda-h100/13.3.1 (a preproduction module PSC specifically aliases for
# H100 nodes) matches what the installed torch/vllm/flashinfer wheels were
# built against and resolved it, confirmed on a real H100 allocation.
module load pytorch/26.05-2.11-py3
unset VIRTUAL_ENV
module load cuda-h100/13.3.1

# The same JIT-compile step also shells out to a bare `ninja` (not a full
# path) -- installed into the vllm venv (see setup_env.sh) but invisible to
# that subprocess unless the venv's own bin/ is actually on PATH, which
# invoking "$VLLM_PYTHON/vllm" by full path alone does not provide. Found
# via a real first job submission failing with FileNotFoundError: 'ninja'
# even after the CUDA module fix above.
export PATH="$VLLM_PYTHON:$PATH"

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
# --max-model-len caps KV cache reservation. Found for real: Qwen3-Coder's
# default 262144 (256K) max context needs 24GiB of KV cache, more than fits
# after ~60GB of fp16 weights on an 80GB H100 (only ~12.4GiB was left,
# causing a real ValueError on the first fp16 job submission). This eval's
# real prompts (schema context + one question) are on the order of a few
# thousand tokens at most (docs/schema.md is ~4.6KB) -- 8192 leaves ample
# headroom while shrinking the KV cache requirement to well under 1GiB.
"$VLLM_PYTHON/vllm" serve "$REPO_ID" \
    --port 8000 \
    --tensor-parallel-size "$TP_SIZE" \
    --max-model-len 8192 \
    > vllm_server.out 2> vllm_server.err &
VLLM_PID=$!
trap 'kill "$VLLM_PID" 2>/dev/null || true' EXIT

echo "Waiting for vllm to be ready (checkpoint download + load can take well over 10 minutes)..."
for i in $(seq 1 360); do
    # Fail fast on an early crash instead of silently polling a dead
    # server for the full 30-minute timeout -- found for real on the
    # first job submission, where vllm crashed within ~1 minute but the
    # loop (checking only curl) burned the whole 30 minutes anyway.
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        echo "vllm process exited after attempt $i -- see vllm_server.err below." >&2
        echo "--- vllm_server.err (full) ---" >&2
        cat vllm_server.err >&2 || true
        exit 1
    fi
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        echo "vllm is ready."
        break
    fi
    if [ "$i" -eq 360 ]; then
        echo "vllm did not become ready after 360 attempts (30 min) -- aborting." >&2
        # Full file, not a tail -- vllm's own wrapper exceptions say "See
        # root cause above," and a short tail has twice now cut off the
        # actual error, costing a full debugging round-trip each time.
        echo "--- vllm_server.err (full) ---" >&2
        cat vllm_server.err >&2 || true
        exit 1
    fi
    sleep 5
done

echo "Confirming GPU(s) are actually being used (not silently falling back to CPU)..."
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv

# Results go to a job-specific, gitignored directory -- NOT reports/eval.md, which
# is tracked: an old run left it modified, which made `git pull` abort. Nothing
# a run writes may touch a tracked file.
OUT="reports/runs/${SLURM_JOB_ID:-manual-$(date +%s)}"
mkdir -p "$OUT"

echo "Running eval with LLM_BACKEND=vllm OLLAMA_MODEL=$REPO_ID -> $OUT ..."
LLM_BACKEND=vllm OLLAMA_MODEL="$REPO_ID" uv run python evals/run_eval.py --db data/ledgerql.duckdb --reports-dir "$OUT"

# Provenance: what ran, on which commit, so every figure is attributable.
cat > "$OUT/run_meta.json" <<META
{
  "commit": "$(git rev-parse HEAD)",
  "expected_commit": "$EXPECTED_COMMIT",
  "model": "$REPO_ID",
  "tensor_parallel_size": $TP_SIZE,
  "slurm_job_id": "${SLURM_JOB_ID:-}",
  "host": "$(hostname)",
  "finished_utc": "$(date -u +%FT%TZ)"
}
META

echo ""
echo "Done. Results at (pull back with: ssh bridges2 'cat <path>' > local-file):"
echo "  $ROOT/ledgerql/$OUT/eval.md"
echo "  $ROOT/ledgerql/$OUT/eval_$(date +%Y-%m-%d).jsonl"
echo "  $ROOT/ledgerql/$OUT/run_meta.json"
