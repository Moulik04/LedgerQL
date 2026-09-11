#!/bin/bash
# One-time (idempotent) environment setup for the Phase 5 remote model
# comparison on PSC Bridges-2. Run from a Bridges-2 LOGIN node (OnDemand
# web shell or `ssh bridges2`) -- never inside an sbatch job, since
# whether compute nodes have outbound internet to ollama.com/PyPI is
# unverified and this script needs both.
#
# Everything lives under $HOME (confirmed ~347T on /jet, effectively
# unconstrained), not /ocean/projects/<alloc>/<user>/ -- that project
# allocation is only 10GB total and two ~20GB Ollama models alone would
# not fit there.
#
#   bash scripts/bridges2/setup_env.sh
set -euo pipefail

ROOT="$HOME/ledgerql-bridges2"
OLLAMA_DIR="$ROOT/ollama"
REPO_DIR="$ROOT/ledgerql"

mkdir -p "$ROOT"

# --- Ollama (no root available on shared HPC nodes -- tarball, not the
# systemd-based curl|sh installer) ---
if [ -x "$OLLAMA_DIR/bin/ollama" ]; then
    echo "Ollama already installed at $OLLAMA_DIR/bin/ollama -- skipping."
else
    echo "Installing Ollama (no-root tarball) into $OLLAMA_DIR..."
    mkdir -p "$OLLAMA_DIR"
    curl -L https://ollama.com/download/ollama-linux-amd64.tgz -o /tmp/ollama-linux-amd64.tgz
    tar -C "$OLLAMA_DIR" -xzf /tmp/ollama-linux-amd64.tgz
    rm -f /tmp/ollama-linux-amd64.tgz
fi

export PATH="$OLLAMA_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$OLLAMA_DIR/lib/ollama:${LD_LIBRARY_PATH:-}"

echo "Ollama version: $("$OLLAMA_DIR/bin/ollama" --version)"

# --- LedgerQL repo ---
if [ -d "$REPO_DIR/.git" ]; then
    echo "Repo already cloned at $REPO_DIR -- pulling latest main..."
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout main
    git -C "$REPO_DIR" pull origin main
else
    echo "Cloning LedgerQL into $REPO_DIR..."
    git clone https://github.com/Moulik04/LedgerQL.git "$REPO_DIR"
fi

# --- Python env ---
cd "$REPO_DIR"
if command -v uv >/dev/null 2>&1; then
    echo "uv already available: $(command -v uv)"
else
    echo "Installing uv (no root needed, installs to \$HOME/.local/bin)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --all-groups

# --- Pull both comparison models (large downloads -- do this here, on
# the login node, not inside the GPU job) ---
# ollama serve must be running locally for `ollama pull` to work; start
# it backgrounded just for this setup step, then stop it -- the real
# sbatch job starts its own instance on the GPU node later.
"$OLLAMA_DIR/bin/ollama" serve &
OLLAMA_SETUP_PID=$!
sleep 3

for model in qwen2.5-coder:32b qwen3-coder:30b; do
    if "$OLLAMA_DIR/bin/ollama" list | grep -q "^${model} "; then
        echo "$model already pulled -- skipping."
    else
        echo "Pulling $model (this is a large download, may take a while)..."
        "$OLLAMA_DIR/bin/ollama" pull "$model"
    fi
done

kill "$OLLAMA_SETUP_PID" 2>/dev/null || true
wait "$OLLAMA_SETUP_PID" 2>/dev/null || true

echo ""
echo "Setup complete. Verify with:"
echo "  export PATH=\"$OLLAMA_DIR/bin:\$PATH\""
echo "  export LD_LIBRARY_PATH=\"$OLLAMA_DIR/lib/ollama:\$LD_LIBRARY_PATH\""
echo "  $OLLAMA_DIR/bin/ollama list"
echo "  cd $REPO_DIR && uv run pytest -q"
