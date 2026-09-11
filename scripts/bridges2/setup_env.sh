#!/bin/bash
# One-time (idempotent) environment setup for the Phase 5 remote model
# comparison on PSC Bridges-2. Run from a Bridges-2 LOGIN node (OnDemand
# web shell or `ssh bridges2`) -- never inside an sbatch job, since
# whether compute nodes have outbound internet to huggingface.co/PyPI is
# unverified and this script needs both.
#
# Everything lives under $HOME (confirmed ~347T on /jet, effectively
# unconstrained), not /ocean/projects/<alloc>/<user>/ -- that project
# allocation is only 10GB total and the two model checkpoints alone
# (~20GB AWQ + ~60GB fp16) would not fit there.
#
# vLLM (not Ollama -- LEDGERQL_MASTER_PROMPT.md explicitly prefers it for
# Bridges-2) lives in its OWN venv here, entirely separate from the main
# ledgerql `.venv`/`pyproject.toml` -- vllm+torch+CUDA are heavy,
# GPU-specific dependencies that must never become a required install for
# the 8GB M2 laptop. The eval process itself runs in the main ledgerql
# venv and only needs httpx (already a base dependency) to talk to vLLM
# over HTTP.
#
#   bash scripts/bridges2/setup_env.sh
set -euo pipefail

ROOT="$HOME/ledgerql-bridges2"
VLLM_ENV_DIR="$ROOT/vllm-env"
REPO_DIR="$ROOT/ledgerql"

mkdir -p "$ROOT"

# --- uv (no root needed, installs to $HOME/.local/bin) ---
if command -v uv >/dev/null 2>&1; then
    echo "uv already available: $(command -v uv)"
else
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# --- LedgerQL repo (main venv: small, CPU-only, just talks to vLLM over HTTP) ---
if [ -d "$REPO_DIR/.git" ]; then
    echo "Repo already cloned at $REPO_DIR -- pulling latest main..."
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout main
    git -C "$REPO_DIR" pull origin main
else
    echo "Cloning LedgerQL into $REPO_DIR..."
    git clone https://github.com/Moulik04/LedgerQL.git "$REPO_DIR"
fi
(cd "$REPO_DIR" && uv sync --all-groups)

# --- vLLM's own separate venv ---
if [ -x "$VLLM_ENV_DIR/.venv/bin/vllm" ]; then
    echo "vLLM already installed at $VLLM_ENV_DIR/.venv -- skipping."
else
    echo "Creating a separate venv for vLLM at $VLLM_ENV_DIR..."
    mkdir -p "$VLLM_ENV_DIR"
    (cd "$VLLM_ENV_DIR" && uv venv --python 3.12 && uv pip install --python .venv/bin/python vllm "huggingface_hub[cli]")
fi

echo "vLLM version: $("$VLLM_ENV_DIR/.venv/bin/vllm" --version)"

# --- Pre-download both model checkpoints (large -- do this here, on the
# login node, not inside the GPU job) ---
for repo_id in \
    "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ" \
    "Qwen/Qwen3-Coder-30B-A3B-Instruct"; do
    echo "Downloading $repo_id (skips already-cached files automatically)..."
    "$VLLM_ENV_DIR/.venv/bin/huggingface-cli" download "$repo_id"
done

echo ""
echo "Setup complete. Verify with:"
echo "  $VLLM_ENV_DIR/.venv/bin/vllm --version"
echo "  cd $REPO_DIR && uv run pytest -q"
