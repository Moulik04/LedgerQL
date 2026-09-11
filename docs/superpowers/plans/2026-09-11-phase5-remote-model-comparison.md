# Phase 5 (part 1): Remote Model Comparison on PSC Bridges-2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagent-driven-development is NOT viable for this plan — Tasks 3-6 require running commands on PSC Bridges-2, a cluster this session has no SSH key access to (password-only auth, confirmed via a failed non-interactive connection attempt), so the human partner must run them and report real output back. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `qwen2.5-coder:32b` and `qwen3-coder:30b` through the exact same 103-case gold-set eval LedgerQL already uses locally, on real Bridges-2 GPU hardware, and produce an honest, evidence-based comparison against the existing `qwen2.5-coder:7b` baseline (54.0% execution accuracy / 0.0% hallucinated-number rate / 27.1% abstain precision).

**Architecture:** Zero changes to `ledgerql/` — `OLLAMA_MODEL` is already an env-var override. New standalone tooling under `scripts/bridges2/` clones/copies the repo and data to Bridges-2, installs Ollama in user space (no root on shared HPC nodes), and runs `OLLAMA_MODEL=<model> make eval` inside a SLURM job with Ollama serving on the same GPU node — no tunnel back to this laptop. The user runs every remote command manually and reports real output back into this session, since neither this session nor a dispatched subagent can reach Bridges-2 directly.

**Tech Stack:** Bash (SLURM job scripts), existing LedgerQL Python/Ollama/DuckDB stack (unchanged), PSC Bridges-2 (SLURM, `GPU-shared` partition, V100-32 GPUs).

**Spec:** `docs/superpowers/specs/2026-09-11-phase5-remote-model-comparison-design.md`

## Global Constraints

- No changes to any file under `ledgerql/` — confirmed `OLLAMA_MODEL` is already read from the environment by `generate.py`, `answer.py`, `classify.py`.
- No production/live-pipeline change. The local default stays `qwen2.5-coder:7b`.
- Model pull and Python dependency install happen on the Bridges-2 **login node**, before any `sbatch` submission — never inside the GPU job itself (unverified whether compute nodes have outbound internet; login nodes do).
- Use `--gres=gpu:v100-32:1` on `GPU-shared` — a real, already-working resource string for this account (`mjain10` / `cis260102p`), not the unverified L40S pool.
- Model weights and the Ollama binary live under `$HOME` (`/jet/home/mjain10`, confirmed ~347T, effectively unconstrained) — **not** `/ocean/projects/cis260102p/mjain10/` (confirmed only 10GB total, and two ~20GB models won't fit there).
- One SLURM job per model, not both in one job.
- Report filenames sanitize `:` to `-` (e.g. `qwen2.5-coder-32b`, not `qwen2.5-coder:32b`) for filesystem/`scp` safety.
- Every claimed fact about the cluster (walltime limits, GPU availability, install behavior) gets verified against real command output before a downstream step depends on it — never assumed from the sibling project's docs, which cover a different node type (V100 was used there too, but for training, not Ollama inference) and a different workload.

---

### Task 1: Bridges-2 environment setup script (Ollama + LedgerQL, login-node only)

**Files:**
- Create: `scripts/bridges2/setup_env.sh`
- Create: `docs/bridges2.md`

**Interfaces:**
- Produces: a script that, run from a Bridges-2 login node, leaves behind:
  - `$HOME/ledgerql-bridges2/ollama/bin/ollama` (extracted tarball) with `$HOME/ledgerql-bridges2/ollama/lib/ollama` for `LD_LIBRARY_PATH`
  - `$HOME/ledgerql-bridges2/ledgerql/` — the cloned repo with `uv sync --all-groups` already run (`.venv` present)
  - Ollama models for `qwen2.5-coder:32b` and `qwen3-coder:30b` already pulled (`ollama list` shows both)
  - Idempotent: safe to re-run, skips whatever's already done (same pattern as the sibling project's `setup_env.sh` — check before doing, never blindly re-download/re-clone)

- [ ] **Step 1: Write the setup script**

```bash
cat > scripts/bridges2/setup_env.sh << 'SCRIPT_EOF'
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
SCRIPT_EOF
chmod +x scripts/bridges2/setup_env.sh
```

- [ ] **Step 2: Syntax-check the script locally**

Run: `bash -n scripts/bridges2/setup_env.sh`
Expected: no output, exit code 0 (no pytest equivalent exists for a shell script that only makes sense on a remote cluster this session can't reach — `bash -n` is the real local verification available: it parses the script and would fail on any syntax error before the human ever runs it remotely).

- [ ] **Step 3: Write `docs/bridges2.md`**

This is the durable, verified-facts record for LedgerQL's own Bridges-2 usage (mirroring the sibling project's `docs/bridges2.md` pattern, but for this project — do not copy claims from that file that haven't been independently confirmed for LedgerQL's own workload).

```bash
cat > docs/bridges2.md << 'DOC_EOF'
# PSC Bridges-2 (Phase 5: remote model comparison)

Runs `qwen2.5-coder:32b` and `qwen3-coder:30b` through LedgerQL's real
103-case eval (`make eval`) on Bridges-2 GPU hardware, to compare
against the local `qwen2.5-coder:7b` baseline (54.0% execution
accuracy / 0.0% hallucinated-number rate / 27.1% abstain precision).
See `docs/superpowers/specs/2026-09-11-phase5-remote-model-comparison-design.md`
for the full design and why.

Everything below is filled in with real, verified output as this
phase's tasks run -- nothing here is assumed from the sibling
ReorderPoint project's own `docs/bridges2.md`, even where the account
(`mjain10` / `cis260102p`) and hardware pool (V100-32 on `GPU-shared`)
are the same. That project's V100 job was training a deep model, not
serving Ollama for inference -- worth re-confirming independently.

## Access

Login: `bridges2.psc.edu` (SSH config alias `bridges2` on the local
machine), or the Open OnDemand web portal
(https://ondemand.bridges2.psc.edu/, browser-based shell under
Clusters -- no SSH key needed). Password-only auth confirmed: this
session's non-interactive `ssh -o BatchMode=yes bridges2` attempt
returned `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password)`.
No SSH key is registered with PSC's key manager, by the human
partner's own choice (see the design spec) -- every command in this
doc is run manually by the human partner, who reports real output
back.

## Storage layout for this phase

- Ollama binary + both models + the LedgerQL repo/venv all live under
  `$HOME/ledgerql-bridges2/` (on `/jet`, confirmed ~347T free in the
  sibling project's own exploration -- effectively unconstrained).
- **Not** `/ocean/projects/cis260102p/mjain10/` -- that allocation is
  only 10GB total, and `qwen2.5-coder:32b` (20GB) +
  `qwen3-coder:30b` (19GB) alone would not fit.

## GPU: `--gres=gpu:v100-32:1` on `GPU-shared`

Reuses the sibling project's already-working resource string for this
exact account, rather than the unverified L40S pool -- see the design
spec's "Hardware" section for the full reasoning.

## Status

<!-- Filled in by Tasks 3-6 as real commands are run and real output
     comes back. Do not write speculative numbers here. -->
DOC_EOF
```

- [ ] **Step 4: Commit**

```bash
git add scripts/bridges2/setup_env.sh docs/bridges2.md
git commit -m "$(cat <<'EOF'
feat(bridges2): add login-node setup script for the Phase 5 model comparison

Installs Ollama via the no-root Linux tarball (no sudo on shared HPC
login nodes -- confirmed pattern from ollama/ollama#7421 and #2111,
not the systemd-based curl|sh installer), clones LedgerQL, runs uv
sync, and pulls both comparison models (qwen2.5-coder:32b,
qwen3-coder:30b). Everything lives under $HOME, not the 10GB
/ocean/projects/ allocation, since the two models alone are ~40GB
combined.

Idempotent -- safe to re-run, checks before re-downloading/re-cloning,
matching the sibling ReorderPoint project's setup_env.sh pattern.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: SLURM job scripts (one job per model)

**Files:**
- Create: `scripts/bridges2/run_model_eval.sh`
- Create: `scripts/bridges2/run_model_eval.sbatch`

**Interfaces:**
- Consumes: `$HOME/ledgerql-bridges2/{ollama,ledgerql}` from Task 1, `data/ledgerql.duckdb` copied into `$HOME/ledgerql-bridges2/ledgerql/data/` by the human partner before submission (Task 4/5's first step — gitignored, not part of the git clone).
- Produces: `reports/eval_bridges2_<sanitized-model>.md` and `reports/eval_bridges2_<sanitized-model>_<date>.jsonl` inside `$HOME/ledgerql-bridges2/ledgerql/`, for the human partner to `scp` back afterward.

- [ ] **Step 1: Write the job body script**

Kept separate from the `.sbatch` file so it can be tested independently of SLURM (matches the sibling project's split between `.sbatch` wrapper and `.py`/`.sh` task script).

```bash
cat > scripts/bridges2/run_model_eval.sh << 'SCRIPT_EOF'
#!/bin/bash
# Job body for the Phase 5 model comparison. Invoked by
# run_model_eval.sbatch inside an active SLURM allocation with a real
# GPU -- do not run this directly on a login node (no GPU there, Ollama
# will fall back to CPU and this will be far slower than intended, or
# just misleading to compare against a GPU-run baseline).
#
# Usage: run_model_eval.sh <ollama-model-tag>
#   e.g. run_model_eval.sh qwen2.5-coder:32b
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <ollama-model-tag>" >&2
    exit 1
fi
MODEL="$1"
SANITIZED_MODEL="${MODEL//:/-}"

ROOT="$HOME/ledgerql-bridges2"
export PATH="$ROOT/ollama/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT/ollama/lib/ollama:${LD_LIBRARY_PATH:-}"

cd "$ROOT/ledgerql"

if [ ! -f data/ledgerql.duckdb ]; then
    echo "data/ledgerql.duckdb not found -- copy it over first (see docs/bridges2.md)." >&2
    exit 1
fi

if ! "$ROOT/ollama/bin/ollama" list | grep -q "^${MODEL} "; then
    echo "$MODEL not found in 'ollama list' -- run scripts/bridges2/setup_env.sh first." >&2
    exit 1
fi

echo "Starting ollama serve..."
"$ROOT/ollama/bin/ollama" serve &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null || true' EXIT

echo "Waiting for ollama to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
        echo "ollama is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ollama did not become ready after 30 attempts (30s) -- aborting." >&2
        exit 1
    fi
    sleep 1
done

echo "Confirming GPU is actually being used (not silently falling back to CPU)..."
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv

echo "Running eval with OLLAMA_MODEL=$MODEL ..."
OLLAMA_MODEL="$MODEL" uv run python evals/run_eval.py --db data/ledgerql.duckdb

DATE_STAMP="$(date +%Y-%m-%d)"
cp reports/eval.md "reports/eval_bridges2_${SANITIZED_MODEL}.md"
cp "reports/eval_${DATE_STAMP}.jsonl" "reports/eval_bridges2_${SANITIZED_MODEL}_${DATE_STAMP}.jsonl"

echo ""
echo "Done. Results at:"
echo "  $ROOT/ledgerql/reports/eval_bridges2_${SANITIZED_MODEL}.md"
echo "  $ROOT/ledgerql/reports/eval_bridges2_${SANITIZED_MODEL}_${DATE_STAMP}.jsonl"
SCRIPT_EOF
chmod +x scripts/bridges2/run_model_eval.sh
```

- [ ] **Step 2: Syntax-check locally**

Run: `bash -n scripts/bridges2/run_model_eval.sh`
Expected: no output, exit code 0.

- [ ] **Step 3: Write the sbatch wrapper**

Walltime and `--gres` here are starting values from the Global
Constraints — Task 3 verifies the partition's real walltime limit
before the first real submission and adjusts this file if needed.

```bash
cat > scripts/bridges2/run_model_eval.sbatch << 'SBATCH_EOF'
#!/bin/bash
#SBATCH --job-name=ledgerql-eval
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

set -euo pipefail

if [ -z "${MODEL:-}" ]; then
    echo "MODEL env var not set -- submit with: sbatch --export=MODEL=qwen2.5-coder:32b run_model_eval.sbatch" >&2
    exit 1
fi

cd "$SLURM_SUBMIT_DIR"
bash scripts/bridges2/run_model_eval.sh "$MODEL"
SBATCH_EOF
```

- [ ] **Step 4: Syntax-check locally**

Run: `bash -n scripts/bridges2/run_model_eval.sbatch`
Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add scripts/bridges2/run_model_eval.sh scripts/bridges2/run_model_eval.sbatch
git commit -m "$(cat <<'EOF'
feat(bridges2): add the SLURM job scripts for the model comparison run

run_model_eval.sh is the job body (kept separate from the .sbatch
wrapper so it's testable on its own): starts ollama serve on the
allocated GPU node, health-checks it via the real /api/version
endpoint rather than a fixed sleep, confirms the GPU is actually in
use via nvidia-smi (not silently falling back to CPU), runs the
existing make eval machinery unchanged via OLLAMA_MODEL, then copies
the report files to model-tagged names so a second model's run
doesn't clobber the first.

Starting --time=02:00:00 and --gres=gpu:v100-32:1 -- Task 3 verifies
the partition's real walltime limit against a live run before the
first real submission and adjusts this file if the estimate is wrong,
rather than guessing further.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Verify cluster facts before the first real submission

**Files:** none created/modified in this task except `docs/bridges2.md`'s Status section (append, don't rewrite the whole file).

**Interfaces:**
- Consumes: `docs/bridges2.md` from Task 1 (has a `<!-- Filled in by Tasks 3-6 -->` placeholder in Status).
- Produces: confirmed real facts that Task 4/5 depend on — the actual GPU resource string, the partition's walltime ceiling, and that the no-root Ollama install genuinely runs on a Bridges-2 GPU node before committing a full ~103-case run to it.

This task is a verification gate, not code — its "test" is real command output from the human partner, run on Bridges-2. Hand the human partner this exact block and wait for their reply with the real output before proceeding.

- [ ] **Step 1: Hand off the verification commands**

```bash
# From a Bridges-2 login node (ssh bridges2, or the OnDemand web shell):

# 1. Confirm the real GPU resource string and availability on GPU-shared
sinfo -N -p GPU-shared -o "%N %G"

# 2. Confirm the partition's real walltime ceiling
scontrol show partition GPU-shared | grep -i maxtime

# 3. Run the setup script (Task 1) if not already done
bash ~/ledgerql-bridges2/ledgerql/scripts/bridges2/setup_env.sh
# (first run: clones the repo to ~/ledgerql-bridges2/ledgerql -- if this
# is truly the first time, `cd` there first or adjust the path above to
# wherever it was cloned)

# 4. Smoke-test Ollama actually starts and serves on a real GPU
#    allocation, before committing a full ~103-case run to it. This is
#    a short interactive allocation, not a batch job.
srun --partition=GPU-shared --gres=gpu:v100-32:1 --time=00:10:00 --pty bash
# (once the allocation starts, inside it:)
export PATH="$HOME/ledgerql-bridges2/ollama/bin:$PATH"
export LD_LIBRARY_PATH="$HOME/ledgerql-bridges2/ollama/lib/ollama:$LD_LIBRARY_PATH"
ollama serve &
sleep 3
curl -sf http://localhost:11434/api/version
nvidia-smi --query-gpu=name,memory.total --format=csv
ollama run qwen2.5-coder:32b "SELECT 1;" --verbose
exit  # ends the interactive allocation
```

- [ ] **Step 2: Record the real output**

Wait for the human partner to paste back the real output of all four
commands above. Do not proceed to Task 4 on assumed output.

- [ ] **Step 3: Reconcile against Global Constraints and fix any mismatch**

- If Step 1's `sinfo` output shows a different real GRES string than
  `gpu:v100-32:1` for this account/partition today, update
  `scripts/bridges2/run_model_eval.sbatch`'s `--gres` line to match
  and re-run the Step 2 syntax check from Task 2.
- If `scontrol`'s maxtime is less than the `--time=02:00:00` currently
  in the sbatch file, lower it to fit (and flag to the human partner
  that a shorter time budget may mean this task should split into more
  than one job per model, or that the plan's wall-time assumption
  needs revisiting before Task 4).
- If `ollama run` in the smoke test fails (GPU not detected, library
  load error, etc.), do not proceed to a full job submission — this is
  exactly the kind of real, unverified risk the design spec called out
  explicitly; debug it here, in a cheap 10-minute interactive
  allocation, not inside a 2-hour batch job.

- [ ] **Step 4: Append the confirmed facts to `docs/bridges2.md`**

Replace the `<!-- Filled in by Tasks 3-6 -->` placeholder comment in
the Status section with a dated entry for the real findings from
Steps 1-3 (exact GRES string, exact maxtime, confirmation the smoke
test passed and what it showed). Tasks 4-6 each add their own further
dated entry below this one — the Status section is a growing log, not
a single value to overwrite again later. Then commit:

```bash
git add docs/bridges2.md
git commit -m "$(cat <<'EOF'
docs(bridges2): record verified cluster facts before the first real run

GPU resource string, GPU-shared's real walltime ceiling, and a
successful no-root Ollama smoke test on a real Bridges-2 GPU
allocation, confirmed via live commands rather than assumed from the
sibling project's docs.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Real run — `qwen2.5-coder:32b`

**Files:** none created/modified except `docs/bridges2.md`'s Status section.

**Interfaces:**
- Consumes: the verified sbatch script from Task 2/3, `data/ledgerql.duckdb` (copied by the human partner).
- Produces: `reports/eval_bridges2_qwen2.5-coder-32b.md` and its dated jsonl, on Bridges-2, then copied to this laptop.

- [ ] **Step 1: Hand off the submission commands**

```bash
# From this laptop, copy the DB over (gitignored, not part of the clone):
scp data/ledgerql.duckdb bridges2:~/ledgerql-bridges2/ledgerql/data/ledgerql.duckdb

# From the Bridges-2 login node:
cd ~/ledgerql-bridges2/ledgerql
sbatch --export=MODEL=qwen2.5-coder:32b scripts/bridges2/run_model_eval.sbatch
squeue -u $USER   # note the job ID, wait for it to clear
```

- [ ] **Step 2: Wait for the job, then hand off the log-retrieval commands**

```bash
cat ledgerql-eval_<jobid>.out
cat ledgerql-eval_<jobid>.err
```

- [ ] **Step 3: Record the real output**

Wait for the human partner to paste back both log files. Before
treating the run as successful:
- Confirm the `.err` file has no unhandled traceback.
- Confirm the `.out` file's `nvidia-smi` output shows non-zero
  `memory.used` (proof the GPU was actually exercised, not silently
  idle while Ollama fell back to CPU).
- Confirm the printed `Overall execution accuracy` /
  `Hallucinated-number rate` lines are present (the script's final
  echo lines from Task 2).

If the job failed or the GPU wasn't used, debug from the real error
before re-submitting — do not guess at a fix.

- [ ] **Step 4: Bring the results back**

```bash
# From this laptop:
scp bridges2:~/ledgerql-bridges2/ledgerql/reports/eval_bridges2_qwen2.5-coder-32b.md reports/
scp "bridges2:~/ledgerql-bridges2/ledgerql/reports/eval_bridges2_qwen2.5-coder-32b_*.jsonl" reports/
```

- [ ] **Step 5: Read the real report and sanity-check it**

Read `reports/eval_bridges2_qwen2.5-coder-32b.md`. Pull 3-5 real
per-case records from the jsonl the same way Phase 4's Task 7 did —
spot-check that the hallucinated-number rate and execution accuracy
are internally consistent with the actual answers/rows shown, not
just trusted as an aggregate. A different inference backend (CUDA
V100 vs. this laptop's Metal) is a new variable that hasn't been
exercised in this project before; do not skip this step even if the
numbers look plausible.

- [ ] **Step 6: Record the real numbers in `docs/bridges2.md` and commit**

```bash
git add docs/bridges2.md reports/eval_bridges2_qwen2.5-coder-32b.md
git commit -m "$(cat <<'EOF'
docs(bridges2): record the real qwen2.5-coder:32b comparison run

Real 103-case eval on a Bridges-2 V100-32 node. <fill in the actual
execution accuracy / hallucinated-number rate / abstain precision
numbers and wall time here, plus a one-line note on the Step 5
spot-check findings>.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

(The dated jsonl stays local/untracked, matching the existing
`reports/*.jsonl` gitignore pattern — only the `.md` report and the
`docs/bridges2.md` narrative get committed.)

---

### Task 5: Real run — `qwen3-coder:30b`

**Files:** none created/modified except `docs/bridges2.md`'s Status section.

**Interfaces:**
- Consumes: same as Task 4.
- Produces: `reports/eval_bridges2_qwen3-coder-30b.md` and its dated jsonl.

- [ ] **Step 0: Check the remaining SU balance before spending more of it**

Hand off: check the OnDemand portal's balance banner (or `projects` /
`sacctmgr` if the human partner prefers a command). The design spec's
account had ~481/500 SU before this phase started — confirm there's
still a reasonable balance left after Task 4's run before committing
to a second multi-hour GPU job. Note from the sibling project's own
verified experience: the balance banner shows SU **remaining**, not
used — a reading like "9.9/10" for the separate, unrelated 10GB
storage allocation means nearly all of it is still free, not nearly
exhausted; don't misread the analogous SU banner the same way.

Repeat Task 4's Steps 1-6 exactly, substituting `qwen3-coder:30b` for
`qwen2.5-coder:32b` everywhere (the `sbatch --export=MODEL=...` value,
the report filenames, the `docs/bridges2.md`/commit content — append a
further dated entry to the Status section, same as Task 4 did, not a
replacement of it). Do not skip Step 5's spot-check just because Task
4's already passed — a different model can fail in different ways.

- [ ] **Step 1: Hand off submission commands** (same shape as Task 4 Step 1, `MODEL=qwen3-coder:30b`; the DB is already copied from Task 4, no need to re-`scp` it)
- [ ] **Step 2: Wait, hand off log-retrieval commands**
- [ ] **Step 3: Record and verify real output**
- [ ] **Step 4: Bring results back** (`eval_bridges2_qwen3-coder-30b.md` / `.jsonl`)
- [ ] **Step 5: Sanity-check real per-case records**
- [ ] **Step 6: Record real numbers in `docs/bridges2.md`, commit**

---

### Task 6: Comparison report and recommendation

**Files:**
- Create: `reports/phase5_model_comparison.md`
- Modify: `.gitignore` (whitelist the new report, matching the existing `!reports/eval.md` pattern)
- Modify: `DECISIONS.md`

**Interfaces:**
- Consumes: the three real report sets — the existing local
  `qwen2.5-coder:7b` baseline (`reports/eval.md`, already committed)
  and the two Bridges-2 reports from Tasks 4-5.
- Produces: a durable, committed comparison and a clear recommendation
  for whether Phase 6 (fine-tuning) or a bigger default model is worth
  pursuing next — this is the deliverable the whole phase exists to
  produce.

- [ ] **Step 1: Whitelist the new report in `.gitignore`**

Find the existing block:
```
# Reports (generated by make eval, not source)
reports/*.md
!reports/baseline.md
!reports/eval.md
reports/*.jsonl
!reports/.gitkeep
```

Change it to:
```
# Reports (generated by make eval, not source)
reports/*.md
!reports/baseline.md
!reports/eval.md
!reports/phase5_model_comparison.md
reports/*.jsonl
!reports/.gitkeep
```

(The per-model `eval_bridges2_*.md` files from Tasks 4-5 stay
gitignored under `reports/*.md` — they're raw per-run snapshots
already folded into this one comparison doc, not separately-maintained
artifacts the way `eval.md` is.)

- [ ] **Step 2: Write the comparison report**

Pull the real numbers from Tasks 4-5's `docs/bridges2.md` entries and
the existing `reports/eval.md` — do not re-derive or re-type numbers
by memory; copy them from the committed source.

```bash
cat > reports/phase5_model_comparison.md << 'EOF'
# Phase 5: Remote Model Comparison

Real 103-case eval (`evals/gold.jsonl`) run against three models,
same guardrails/self-consistency/verifier pipeline, same seed. The
7B run is local (M2, Metal); the 32B and 30B runs are on PSC
Bridges-2 (V100-32 GPU) — see `docs/bridges2.md` for the real,
verified cluster setup.

| Model | Execution accuracy | Hallucinated-number rate | Abstain precision | Wall time |
|---|---|---|---|---|
| qwen2.5-coder:7b (local, existing baseline) | 54.0% | 0.0% | 27.1% | <fill in from earlier phase notes if known, else "not timed"> |
| qwen2.5-coder:32b (Bridges-2) | <fill in> | <fill in> | <fill in> | <fill in> |
| qwen3-coder:30b (Bridges-2) | <fill in> | <fill in> | <fill in> | <fill in> |

## Findings

<Fill in honestly from the real numbers -- did either bigger model
meaningfully improve accuracy or abstain precision? By how much? Was
the improvement (if any) large enough to justify the operational cost
of a bigger model (no longer runs on the 8GB local machine; would need
a standing remote-inference setup for production use, which this
phase deliberately did not build)?>

## Recommendation

<One of, chosen honestly from the real evidence, not decided in
advance:
- "A bigger model meaningfully helps -- worth a follow-up phase to
  design a standing remote-inference setup for production use."
- "A bigger model does not meaningfully help -- the bottleneck is
  elsewhere (ambiguous questions, hard-query self-consistency,
  structural abstain-precision gaps already documented in
  DECISIONS.md). Phase 6 (fine-tuning) should be re-scoped around
  that finding, not treated as `qwen2.5-coder:7b`'s fault, and
  building a bigger-model production path is not worth the
  operational cost."
- something in between, stated precisely with the real numbers behind
  it.>
EOF
```

- [ ] **Step 3: Add the `DECISIONS.md` entry**

Read the existing entries first (e.g. the 2026-09-11 entries from
Phase 4's final review) to match voice/structure exactly — Context /
Options / Decision / Consequence. Append (do not overwrite existing
content):

```bash
cat >> DECISIONS.md << 'EOF'

---

## <today's date> — Phase 5 model comparison: <one-line real finding>

**Context:** <fill in from the real numbers in
reports/phase5_model_comparison.md>

**Options:**
- <the real options weighed, given the real numbers>

**Decision:** <the real decision, matching
reports/phase5_model_comparison.md's Recommendation section>

**Consequence:** <what this means for Phase 6 and for the live
pipeline's default model going forward>
EOF
```

- [ ] **Step 4: Update the top-level `README.md` roadmap line for Phase 5**

Find the Phase 5 line (currently `- [ ] **Phase 5 — Scale-out evals.**
Larger model comparison on GPU infrastructure, expanded gold set.`)
and check it off with the real one-line finding, matching the exact
style already used for Phases 1-4's roadmap lines.

- [ ] **Step 5: Run the full local test suite one more time**

Run: `uv run pytest -q`
Expected: all tests still passing (this task touched no `ledgerql/`
code, only docs/reports/gitignore, so this should be unaffected — run
it anyway rather than assume).

- [ ] **Step 6: Commit**

```bash
git add reports/phase5_model_comparison.md .gitignore DECISIONS.md README.md
git commit -m "$(cat <<'EOF'
docs: Phase 5 model comparison report and recommendation

<one-line summary of the real finding and recommendation>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Push**

```bash
git push
```

(This plan works directly on `main`, not a feature branch — every
task's changes are docs/scripts/reports, not application code, and
each commit is independently safe to have on `main` even mid-plan,
matching how `finishing-a-development-branch` would have nothing
meaningful to merge here.)
