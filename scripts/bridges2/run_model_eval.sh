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

# Per-job server logs: concurrent jobs share this checkout, and a fixed name let
# four jobs overwrite each other (a failed job's server log was unrecoverable).
VLLM_OUT="vllm_server_${SLURM_JOB_ID:-manual}.out"
VLLM_ERR="vllm_server_${SLURM_JOB_ID:-manual}.err"
# Jobs share nodes (GPU-shared partition), and every job used to serve on one fixed port. Two jobs on one
# node then talk to each other's server: 47314850's smoke requests were answered by 47314848's
# server (404, wrong model), and 47314853's own server failed to bind and it ran against another
# job's server until that job exited, leaving 27 of 103 records as "connection refused". So each
# job picks a port nothing is listening on, and checks below that the server it reaches is its own.
pick_free_port() {
    python3 - <<'PY'
import socket

s = socket.socket()
s.bind(("0.0.0.0", 0))
print(s.getsockname()[1])
s.close()
PY
}
PORT=$(pick_free_port)
export VLLM_PORT="$PORT"
echo "Starting vllm serve for $REPO_ID (tensor-parallel-size=$TP_SIZE)..."
echo "First run downloads the checkpoint into \$LOCAL ($LOCAL) -- this can take a while on top of model-load time."
# --max-model-len caps KV cache reservation. Found for real: Qwen3-Coder's
# default 262144 (256K) max context needs 24GiB of KV cache, more than fits
# after ~60GB of fp16 weights on an 80GB H100 (only ~12.4GiB was left,
# causing a real ValueError on the first fp16 job submission). This eval's
# real prompts (schema context + one question) are on the order of a few
# thousand tokens at most (docs/schema.md is ~4.6KB) -- 8192 leaves ample
# headroom while shrinking the KV cache requirement to well under 1GiB.
# MAX_MODEL_LEN overrides the 8192 default; the generation-only bake-off jobs set
# it per job, sized from their longest prompt (see the *_genonly.sbatch files).
"$VLLM_PYTHON/vllm" serve "$REPO_ID" \
    --port "$PORT" \
    --tensor-parallel-size "$TP_SIZE" \
    --max-model-len "${MAX_MODEL_LEN:-8192}" \
    ${VLLM_EXTRA_ARGS:-} \
    > "$VLLM_OUT" 2> "$VLLM_ERR" &
VLLM_PID=$!
trap 'kill "$VLLM_PID" 2>/dev/null || true' EXIT

echo "Waiting for vllm to be ready (checkpoint download + load can take well over 10 minutes)..."
for i in $(seq 1 360); do
    # Fail fast on an early crash instead of silently polling a dead
    # server for the full 30-minute timeout -- found for real on the
    # first job submission, where vllm crashed within ~1 minute but the
    # loop (checking only curl) burned the whole 30 minutes anyway.
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        echo "vllm process exited after attempt $i -- see $VLLM_ERR below." >&2
        echo "--- vllm_server.err (full) ---" >&2
        cat "$VLLM_ERR" >&2 || true
        exit 1
    fi
    if curl -sf http://localhost:$PORT/health >/dev/null 2>&1; then
        echo "vllm is ready."
        break
    fi
    if [ "$i" -eq 360 ]; then
        echo "vllm did not become ready after 360 attempts (30 min) -- aborting." >&2
        # Full file, not a tail -- vllm's own wrapper exceptions say "See
        # root cause above," and a short tail has twice now cut off the
        # actual error, costing a full debugging round-trip each time.
        echo "--- vllm_server.err (full) ---" >&2
        cat "$VLLM_ERR" >&2 || true
        exit 1
    fi
    sleep 5
done

# The server on this port must be this job's own model. /health only says *something* is serving.
if ! curl -sf "http://localhost:$PORT/v1/models" | grep -q "\"$REPO_ID\""; then
    echo "STOP: the server on port $PORT does not serve $REPO_ID. Models it reports:" >&2
    curl -s "http://localhost:$PORT/v1/models" >&2 || true
    exit 1
fi
echo "Confirmed: port $PORT serves $REPO_ID."

echo "Confirming GPU(s) are actually being used (not silently falling back to CPU)..."
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv

# Results go to a job-specific, gitignored directory -- NOT reports/eval.md, which
# is tracked: an old run left it modified, which made `git pull` abort. Nothing
# a run writes may touch a tracked file.
OUT="reports/runs/${SLURM_JOB_ID:-manual-$(date +%s)}"
mkdir -p "$OUT"

if [ "${EVAL_MODE:-pipeline}" = "gen_only" ]; then
    # Task 9 bake-off: generation only, no classify/answer stage. PROFILES is a
    # space-separated list; the first is the model's native prompt format. A
    # 3-case smoke test on it runs first and, under pipefail, aborts the job
    # (exit 3) unless the model produced executing SQL, so a model that will not
    # load, fit, or emit SQL costs minutes of the allocation, not hours.
    : "${PROFILES:?PROFILES is required when EVAL_MODE=gen_only, e.g. 'xiyan current omnisql'}"
    FIRST_PROFILE="${PROFILES%% *}"
    echo "Smoke test: profile $FIRST_PROFILE, 3 cases x 2 candidates ..."
    uv run python -m evals.gen_only_eval --profile "$FIRST_PROFILE" --model "$REPO_ID" \
        --host http://localhost:$PORT --db data/ledgerql.duckdb --out "$OUT/smoke" \
        --smoke 3 --n 2 | tee "$OUT/smoke.log" || smoke_status=${PIPESTATUS[0]}
    if [ "${smoke_status:-0}" -ne 0 ]; then
        echo "Smoke test FAILED (exit $smoke_status). vllm server log tail ($VLLM_ERR):" >&2
        tail -n 80 "$VLLM_ERR" >&2 || true
        exit "$smoke_status"
    fi
    if [ -n "${SMOKE_ONLY:-}" ]; then
        echo "SMOKE_ONLY set: stopping after the smoke test. Log: $OUT/smoke.log"
    else
        # GOLD_FILE: the gold the run scores against (default: the frozen v3). A held-out
        # file is refused unless it matches its freeze pin (evals/scoring.require_frozen).
        GOLD_FILE="${GOLD_FILE:-evals/gold_v3.jsonl}"
        for profile in $PROFILES; do
            echo "Generation-only eval: profile $profile ..."
            uv run python -m evals.gen_only_eval --profile "$profile" --model "$REPO_ID" \
                --host http://localhost:$PORT --db data/ledgerql.duckdb --out "$OUT" --gold "$GOLD_FILE"
            if [ -n "${ENTITY_LINK_AB:-}" ]; then
                # Entity-linking A/B: the same server session, the same seeds, the same
                # cases, only the resolved-companies hint differs.
                echo "Generation-only eval: profile $profile, WITH --entity-link ..."
                uv run python -m evals.gen_only_eval --profile "$profile" --model "$REPO_ID" \
                    --host http://localhost:$PORT --db data/ledgerql.duckdb --out "$OUT" --gold "$GOLD_FILE" \
                    --entity-link
            fi
        done
    fi
else
    echo "Running eval with LLM_BACKEND=vllm OLLAMA_MODEL=$REPO_ID -> $OUT ..."
    VLLM_HOST="http://localhost:$PORT" LLM_BACKEND=vllm OLLAMA_MODEL="$REPO_ID" \
        uv run python evals/run_eval.py --db data/ledgerql.duckdb --reports-dir "$OUT" \
        --gold "${GOLD_FILE:-evals/gold_v3.jsonl}"
fi

# Provenance: what ran, on which commit, so every figure is attributable.
cat > "$OUT/run_meta.json" <<META
{
  "commit": "$(git rev-parse HEAD)",
  "expected_commit": "$EXPECTED_COMMIT",
  "model": "$REPO_ID",
  "eval_mode": "${EVAL_MODE:-pipeline}",
  "vllm_port": "${PORT:-}",
  "profiles": "${PROFILES:-}",
  "entity_link_ab": "${ENTITY_LINK_AB:-}",
  "gold_file": "${GOLD_FILE:-}",
  "tensor_parallel_size": $TP_SIZE,
  "slurm_job_id": "${SLURM_JOB_ID:-}",
  "host": "$(hostname)",
  "finished_utc": "$(date -u +%FT%TZ)"
}
META

echo ""
echo "Done. Results at (pull back with: ssh bridges2 'cat <path>' > local-file):"
if [ "${EVAL_MODE:-pipeline}" = "gen_only" ]; then
    echo "  $ROOT/ledgerql/$OUT/gen_only_<profile>.{jsonl,md,_summary.json}"
else
    echo "  $ROOT/ledgerql/$OUT/eval.md"
    echo "  $ROOT/ledgerql/$OUT/eval_$(date +%Y-%m-%d).jsonl"
fi
echo "  $ROOT/ledgerql/$OUT/run_meta.json"
