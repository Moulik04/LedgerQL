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

# A local Python interpreter, not a download: real login-node testing found
# `uv sync`'s own standalone-Python auto-download (needed since the system
# python3 is 3.6.8 and the newest `module avail python` offers is 3.8.6 --
# both well below pyproject.toml's requires-python >=3.11) repeatedly failed
# ("Invalid tar file" / "operation timed out" after 3 retries over 26
# minutes) -- large external binary transfers are unreliable from this
# login node. `module load pytorch/26.05-2.11-py3` provides Python 3.13.7 at
# a fixed local path with no download at all (confirmed identically in the
# sibling ReorderPoint project's own setup_env.sh). Loading it also sets
# VIRTUAL_ENV to its own read-only base env -- confirmed in that project to
# confuse `uv venv`/`uv sync` into targeting the wrong environment unless
# explicitly unset.
module load pytorch/26.05-2.11-py3
unset VIRTUAL_ENV
PY_INTERP=/opt/packages/uv/python/cpython-3.13.7-linux-x86_64-gnu

mkdir -p "$ROOT"

# --- uv (no root needed, installs to $HOME/.local/bin; the module above
# also bundles its own uv, but ~/.local/bin's copy works fine standalone
# too and this way the script doesn't depend on the module being loaded
# for every future invocation) ---
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
if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
    (cd "$REPO_DIR" && uv venv --python "$PY_INTERP")
fi
(cd "$REPO_DIR" && uv sync --all-groups)

# --- vLLM's own separate venv ---
if [ -x "$VLLM_ENV_DIR/.venv/bin/vllm" ]; then
    echo "vLLM already installed at $VLLM_ENV_DIR/.venv -- skipping."
else
    echo "Creating a separate venv for vLLM at $VLLM_ENV_DIR..."
    mkdir -p "$VLLM_ENV_DIR"
    (cd "$VLLM_ENV_DIR" && uv venv --python "$PY_INTERP" && uv pip install --python .venv/bin/python vllm "huggingface_hub[cli]")
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
