# Phase 5 (part 1): Remote Model Comparison on PSC Bridges-2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Subagent-driven-development is NOT viable for this plan — Tasks 3-6 require running commands on PSC Bridges-2, a cluster this session has no SSH key access to (password-only auth, confirmed via a failed non-interactive connection attempt), so the human partner must run them and report real output back. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` and `Qwen/Qwen3-Coder-30B-A3B-Instruct` through the exact same 103-case gold-set eval LedgerQL already uses locally, on real Bridges-2 GPU hardware via vLLM, and produce an honest, evidence-based comparison against the existing `qwen2.5-coder:7b` baseline (54.0% execution accuracy / 0.0% hallucinated-number rate / 27.1% abstain precision).

**Architecture:** `ledgerql/llm_backends.py` (already implemented — see Task 1) adds a `VLLMClient` adapter, duck-typed to `ollama.Client`'s own `.generate()` shape, selected via `LLM_BACKEND=vllm`; `generate.py`/`answer.py`/`classify.py`'s own logic is unchanged. New standalone tooling under `scripts/bridges2/` clones/copies the repo and data to Bridges-2, installs vLLM in its own separate venv (no root on shared HPC nodes), and runs `LLM_BACKEND=vllm OLLAMA_MODEL=<repo-id> make eval`-equivalent inside a SLURM job with `vllm serve` running on the same GPU node(s) — no tunnel back to this laptop. The user runs every remote command manually and reports real output back into this session, since neither this session nor a dispatched subagent can reach Bridges-2 directly.

**Tech Stack:** Bash (SLURM job scripts), `ledgerql/llm_backends.py` (httpx-based vLLM adapter, no new base dependency), vLLM + PyTorch (Bridges-2-only, isolated venv), PSC Bridges-2 (SLURM, `GPU-shared` partition, V100-32 GPUs).

**Spec:** `docs/superpowers/specs/2026-09-11-phase5-remote-model-comparison-design.md` (revised after Task 1/2's first draft — see `git log` on that file for why)

## Global Constraints

- The only `ledgerql/` change is `llm_backends.py` and the three one-line call-site edits in `generate.py`/`answer.py`/`classify.py` (done in Task 1). No further application-code changes.
- No production/live-pipeline change. The local default stays `qwen2.5-coder:7b` via Ollama (`LLM_BACKEND` defaults to `"ollama"`).
- Model download and Python dependency install happen on the Bridges-2 **login node**, before any `sbatch` submission — never inside the GPU job itself (unverified whether compute nodes have outbound internet; login nodes do).
- `Qwen2.5-Coder-32B-Instruct-AWQ` uses `--gres=gpu:v100-32:1`; `Qwen3-Coder-30B-A3B-Instruct` (full fp16, no quantization) uses `--gres=gpu:v100-32:2` with `--tensor-parallel-size 2` — both on `GPU-shared`.
- vLLM + its model checkpoints live under `$HOME` (`/jet/home/mjain10`, confirmed ~347T, effectively unconstrained) in their own venv, **separate from the main `ledgerql` `.venv`** — `vllm`/`torch`/CUDA must never become part of the base `pyproject.toml` install the 8GB M2 laptop also uses. Not `/ocean/projects/cis260102p/mjain10/` (confirmed only 10GB total; the two checkpoints alone are ~80GB combined).
- One SLURM job per model, not both in one job.
- Report filenames sanitize both `:` and `/` to `-` (HF repo ids contain `/`) for filesystem/`scp` safety.
- Every claimed fact about the cluster (walltime limits, GPU availability, 2-GPU allocation permission, AWQ kernel support on V100/Volta) gets verified against real command output before a downstream step depends on it — never assumed from the sibling project's docs, which only ever used 1 GPU for training, not inference.

---

### Task 1: `ledgerql/llm_backends.py` (vLLM adapter) — COMPLETE

Done directly in this session (not via the hand-off pattern below, since this is ordinary application code with local tests — TDD, not a remote-verification gate):

- `ledgerql/llm_backends.py`: `VLLMClient` (pure-`httpx` adapter, POSTs to vLLM's OpenAI-compatible `/v1/chat/completions`, returns an object with `.response` matching `ollama.Client.generate()`'s shape) and `default_client()` (reads `LLM_BACKEND` env var fresh on every call — `"vllm"` → `VLLMClient()`, anything else/unset → `ollama.Client(host=OLLAMA_HOST)`, the existing default).
- `generate.py`/`answer.py`/`classify.py`: their `client = client or ollama.Client(host=OLLAMA_HOST)` line replaced with `client = client or llm_backends.default_client()`; type hints widened to `ollama.Client | llm_backends.VLLMClient | None`. No other logic changed.
- `tests/test_llm_backends.py`: 6 new tests (backend selection, request shape, response parsing, missing-options handling, HTTP error propagation) using `httpx.MockTransport` — no real network calls.
- Verified: 154/154 tests passing (148 existing + 6 new), `ruff`/`black` clean.

Commit: `5bb8854` — `feat: add a vLLM backend option alongside the existing Ollama default`.

---

### Task 2: Bridges-2 scripts (vLLM setup + SLURM jobs) — COMPLETE

Done directly in this session:

- `scripts/bridges2/setup_env.sh`: clones the repo, `uv sync`s the main venv (small, CPU-only — only needs `httpx` to talk to vLLM), creates a **separate** venv at `$HOME/ledgerql-bridges2/vllm-env` and installs `vllm` + `huggingface_hub[cli]` into it, pre-downloads both model checkpoints via `huggingface-cli download` on the login node. Idempotent.
- `docs/bridges2.md`: durable, verified-facts record (access method, storage layout, GPU resource strings for each model) — rewritten from Task 1's original Ollama-based draft. Status section still has the `<!-- Filled in by Tasks 3-6 -->` placeholder.
- `scripts/bridges2/run_model_eval.sh`: shared job body, `Usage: run_model_eval.sh <hf-repo-id> <tensor-parallel-size>`. Starts `vllm serve <repo-id> --port 8000 --tensor-parallel-size <N>`, health-checks the real `/health` endpoint (up to 10 minutes — large checkpoints take a while to load, unlike Ollama's near-instant startup), confirms GPU usage via `nvidia-smi`, runs `LLM_BACKEND=vllm OLLAMA_MODEL=<repo-id> uv run python evals/run_eval.py --db data/ledgerql.duckdb` in the main `ledgerql` venv, copies results to `reports/eval_bridges2_<sanitized-repo-id>.md` / `..._<date>.jsonl`.
- `scripts/bridges2/run_qwen25_coder_32b_awq.sbatch`: `--gres=gpu:v100-32:1`, `--time=02:00:00`, calls `run_model_eval.sh Qwen/Qwen2.5-Coder-32B-Instruct-AWQ 1`.
- `scripts/bridges2/run_qwen3_coder_30b_fp16.sbatch`: `--gres=gpu:v100-32:2`, `--time=03:00:00`, calls `run_model_eval.sh Qwen/Qwen3-Coder-30B-A3B-Instruct 2`. (Two separate sbatch files, not one MODEL-env-var-driven file — `#SBATCH --gres` is parsed at submission time, not runtime-evaluated from an exported var, and the two models need genuinely different GPU counts.)

All four scripts syntax-checked locally (`bash -n`) — no pytest equivalent exists for shell scripts that only make sense on a cluster this session can't reach.

Commit: `245abf7` — `feat(bridges2): rewrite Bridges-2 scripts for vLLM instead of Ollama`.

---

### Task 3: Verify cluster facts before the first real submission

**Files:** none created/modified in this task except `docs/bridges2.md`'s Status section (append, don't rewrite the whole file).

**Interfaces:**
- Consumes: `docs/bridges2.md` from Task 2 (has a `<!-- Filled in by Tasks 3-6 -->` placeholder in Status).
- Produces: confirmed real facts that Tasks 4-5 depend on — the actual GPU resource string, whether `GPU-shared` permits a 2-GPU request, the partition's walltime ceiling, and that vLLM (including the AWQ quantization kernel, which has real GPU-compute-capability requirements) genuinely runs on a Bridges-2 V100 before committing a full ~103-case run to it.

This task is a verification gate, not code — its "test" is real command output from the human partner, run on Bridges-2. Hand the human partner this exact block and wait for their reply with the real output before proceeding.

- [ ] **Step 1: Hand off the verification commands**

```bash
# From a Bridges-2 login node (ssh bridges2, or the OnDemand web shell):

# 1. Confirm the real GPU resource string and availability on GPU-shared
sinfo -N -p GPU-shared -o "%N %G"

# 2. Confirm the partition's real walltime ceiling
scontrol show partition GPU-shared | grep -i maxtime

# 3. Confirm a 2-GPU request is even permitted on GPU-shared for this account
scontrol show partition GPU-shared | grep -iE "maxnodes|maxcpuspernode|grpjob"
sacctmgr show assoc user=mjain10 account=cis260102p format=user,account,maxjobs,maxsubmit,grpjobs 2>/dev/null || echo "sacctmgr query unavailable, note this down and proceed cautiously"

# 4. Run the setup script (Task 2) if not already done
bash ~/ledgerql-bridges2/ledgerql/scripts/bridges2/setup_env.sh
# (first run: clones the repo to ~/ledgerql-bridges2/ledgerql -- if this
# is truly the first time, `cd` there first or adjust the path above to
# wherever it was cloned)

# 5. Smoke-test vLLM + the AWQ quant actually work on a real V100 GPU
#    allocation, before committing a full ~103-case run to it. This is
#    a short interactive allocation, not a batch job. AWQ kernel support
#    varies by GPU compute capability -- V100 is Volta (compute 7.0),
#    NOT assumed compatible without this real test.
srun --partition=GPU-shared --gres=gpu:v100-32:1 --time=00:15:00 --pty bash
# (once the allocation starts, inside it:)
cd ~/ledgerql-bridges2/vllm-env
.venv/bin/vllm serve Qwen/Qwen2.5-Coder-32B-Instruct-AWQ --port 8000 &
VLLM_SMOKE_PID=$!
sleep 60   # give it real time to load ~20GB of weights before polling
for i in $(seq 1 30); do
    curl -sf http://localhost:8000/health && break
    sleep 10
done
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv
curl -s http://localhost:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"Qwen/Qwen2.5-Coder-32B-Instruct-AWQ","messages":[{"role":"user","content":"Reply with exactly: OK"}]}'
kill $VLLM_SMOKE_PID
exit  # ends the interactive allocation
```

- [ ] **Step 2: Record the real output**

Wait for the human partner to paste back the real output of all five commands above. Do not proceed to Task 4 on assumed output.

- [ ] **Step 3: Reconcile against Global Constraints and fix any mismatch**

- If Step 1's `sinfo` output shows a different real GRES string than `gpu:v100-32` for this account/partition today, update both `.sbatch` files' `--gres` lines to match and re-run their `bash -n` syntax checks.
- If the 2-GPU check in Step 1 shows `GPU-shared` caps per-job GPU count below 2 for this account, flag this immediately — Task 5 (`qwen3-coder`, needs 2 GPUs) cannot proceed as planned; options become requesting the full `GPU` partition instead of `GPU-shared`, or dropping that model from this round. Do not guess; ask the human partner how to proceed once this is confirmed.
- If `scontrol`'s maxtime is less than either `.sbatch` file's `--time`, lower it to fit and flag whether this fits the workload.
- If the vLLM smoke test fails (AWQ kernel unsupported on V100, CUDA/driver mismatch, out-of-memory, etc.), do not proceed to a full job submission — debug it here, in a cheap 15-minute interactive allocation, not inside a 2-hour batch job. A common real failure mode worth checking for specifically: AWQ's Marlin/GPTQ-style kernels sometimes require compute capability ≥ 7.5 or ≥ 8.0 depending on the vLLM version — if V100 (7.0) is unsupported, the fallback is running `Qwen2.5-Coder-32B-Instruct` unquantized... which does not fit 32GB, so the real fallback would be dropping to a smaller model or requesting 2 GPUs for this one too. Surface this to the human partner rather than deciding unilaterally.

- [ ] **Step 4: Append the confirmed facts to `docs/bridges2.md`**

Replace the `<!-- Filled in by Tasks 3-6 -->` placeholder comment in the Status section with a dated entry for the real findings from Steps 1-3 (exact GRES string, exact maxtime, 2-GPU permission confirmed or not, confirmation the vLLM/AWQ smoke test passed and what it showed). Tasks 4-6 each add their own further dated entry below this one — the Status section is a growing log, not a single value to overwrite again later. Then commit:

```bash
git add docs/bridges2.md
git commit -m "$(cat <<'EOF'
docs(bridges2): record verified cluster facts before the first real run

GPU resource string, GPU-shared's real walltime ceiling, 2-GPU
allocation permission, and a successful vLLM + AWQ smoke test on a
real Bridges-2 V100 allocation, confirmed via live commands rather
than assumed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Real run — `Qwen2.5-Coder-32B-Instruct-AWQ`

**Files:** none created/modified except `docs/bridges2.md`'s Status section.

**Interfaces:**
- Consumes: the verified sbatch script from Task 2/3, `data/ledgerql.duckdb` (copied by the human partner).
- Produces: `reports/eval_bridges2_Qwen-Qwen2.5-Coder-32B-Instruct-AWQ.md` and its dated jsonl, on Bridges-2, then copied to this laptop.

- [ ] **Step 1: Hand off the submission commands**

```bash
# From this laptop, copy the DB over (gitignored, not part of the clone):
scp data/ledgerql.duckdb bridges2:~/ledgerql-bridges2/ledgerql/data/ledgerql.duckdb

# From the Bridges-2 login node:
cd ~/ledgerql-bridges2/ledgerql
sbatch scripts/bridges2/run_qwen25_coder_32b_awq.sbatch
squeue -u $USER   # note the job ID, wait for it to clear
```

- [ ] **Step 2: Wait for the job, then hand off the log-retrieval commands**

```bash
cat ledgerql-eval-32b_<jobid>.out
cat ledgerql-eval-32b_<jobid>.err
```

- [ ] **Step 3: Record the real output**

Wait for the human partner to paste back both log files. Before treating the run as successful:
- Confirm the `.err` file has no unhandled traceback.
- Confirm the `.out` file's `nvidia-smi` output shows non-zero `memory.used` (proof the GPU was actually exercised, not silently idle).
- Confirm the printed `Overall execution accuracy` / `Hallucinated-number rate` lines are present (the script's final echo lines from Task 2).

If the job failed or the GPU wasn't used, debug from the real error before re-submitting — do not guess at a fix.

- [ ] **Step 4: Bring the results back**

```bash
# From this laptop:
scp bridges2:~/ledgerql-bridges2/ledgerql/reports/eval_bridges2_Qwen-Qwen2.5-Coder-32B-Instruct-AWQ.md reports/
scp "bridges2:~/ledgerql-bridges2/ledgerql/reports/eval_bridges2_Qwen-Qwen2.5-Coder-32B-Instruct-AWQ_*.jsonl" reports/
```

- [ ] **Step 5: Read the real report and sanity-check it**

Read the report. Pull 3-5 real per-case records from the jsonl the same way Phase 4's Task 7 did — spot-check that the hallucinated-number rate and execution accuracy are internally consistent with the actual answers/rows shown, not just trusted as an aggregate. A different inference backend (CUDA V100 via vLLM vs. this laptop's Metal via Ollama) is a new variable that hasn't been exercised in this project before; do not skip this step even if the numbers look plausible.

- [ ] **Step 6: Record the real numbers in `docs/bridges2.md` and commit**

```bash
git add docs/bridges2.md reports/eval_bridges2_Qwen-Qwen2.5-Coder-32B-Instruct-AWQ.md
git commit -m "$(cat <<'EOF'
docs(bridges2): record the real Qwen2.5-Coder-32B-Instruct-AWQ comparison run

Real 103-case eval on a Bridges-2 V100-32 node via vLLM. <fill in the
actual execution accuracy / hallucinated-number rate / abstain
precision numbers and wall time here, plus a one-line note on the
Step 5 spot-check findings>.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

(The dated jsonl stays local/untracked, matching the existing `reports/*.jsonl` gitignore pattern — only the `.md` report and the `docs/bridges2.md` narrative get committed.)

---

### Task 5: Real run — `Qwen3-Coder-30B-A3B-Instruct` (fp16, 2 GPUs)

**Files:** none created/modified except `docs/bridges2.md`'s Status section.

**Interfaces:**
- Consumes: same as Task 4, plus Task 3's confirmation that a 2-GPU request is permitted on `GPU-shared` for this account.
- Produces: `reports/eval_bridges2_Qwen-Qwen3-Coder-30B-A3B-Instruct.md` and its dated jsonl.

- [ ] **Step 0: Check the remaining SU balance before spending more of it**

Hand off: check the OnDemand portal's balance banner (or `sacctmgr`/equivalent if the human partner prefers a command). The design spec's account had ~481/500 SU before this phase started — confirm there's still a reasonable balance left after Task 4's run before committing to a second, larger (2-GPU, likely longer) job. Note from the sibling project's own verified experience: the balance banner shows SU **remaining**, not used.

Repeat Task 4's Steps 1-6 exactly, substituting `Qwen/Qwen3-Coder-30B-A3B-Instruct` / `run_qwen3_coder_30b_fp16.sbatch` / `ledgerql-eval-30b_<jobid>` for `Qwen2.5-Coder-32B-Instruct-AWQ` / `run_qwen25_coder_32b_awq.sbatch` / `ledgerql-eval-32b_<jobid>` everywhere (the report filenames, the `docs/bridges2.md`/commit content — append a further dated entry to the Status section, same as Task 4 did, not a replacement of it). Do not skip Step 5's spot-check just because Task 4's already passed — a different model, and a different GPU count/precision, can fail in different ways.

- [ ] **Step 1: Hand off submission commands** (the DB is already copied from Task 4, no need to re-`scp` it)
- [ ] **Step 2: Wait, hand off log-retrieval commands**
- [ ] **Step 3: Record and verify real output** (2-GPU jobs: confirm `nvidia-smi` shows usage on *both* GPU indices, not just one — a job that only exercised 1 of 2 allocated GPUs likely means `--tensor-parallel-size 2` didn't actually take effect)
- [ ] **Step 4: Bring results back**
- [ ] **Step 5: Sanity-check real per-case records**
- [ ] **Step 6: Record real numbers in `docs/bridges2.md`, commit**

---

### Task 6: Comparison report and recommendation

**Files:**
- Create: `reports/phase5_model_comparison.md`
- Modify: `.gitignore` (whitelist the new report, matching the existing `!reports/eval.md` pattern)
- Modify: `DECISIONS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the three real report sets — the existing local `qwen2.5-coder:7b` baseline (`reports/eval.md`, already committed) and the two Bridges-2 reports from Tasks 4-5.
- Produces: a durable, committed comparison and a clear recommendation for whether Phase 6 (fine-tuning) or a bigger default model is worth pursuing next — this is the deliverable the whole phase exists to produce.

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

(The per-model `eval_bridges2_*.md` files from Tasks 4-5 stay gitignored under `reports/*.md` — they're raw per-run snapshots already folded into this one comparison doc.)

- [ ] **Step 2: Write the comparison report**

Pull the real numbers from Tasks 4-5's `docs/bridges2.md` entries and the existing `reports/eval.md` — do not re-derive or re-type numbers by memory; copy them from the committed source.

```bash
cat > reports/phase5_model_comparison.md << 'EOF'
# Phase 5: Remote Model Comparison

Real 103-case eval (`evals/gold.jsonl`) run against three models,
same guardrails/self-consistency/verifier pipeline, same seed. The
7B run is local (M2, Metal, via Ollama); the 32B and 30B runs are on
PSC Bridges-2 (V100-32 GPUs, via vLLM per LEDGERQL_MASTER_PROMPT.md's
explicit preference) — see `docs/bridges2.md` for the real, verified
cluster setup.

| Model | Precision / GPUs | Execution accuracy | Hallucinated-number rate | Abstain precision | Wall time |
|---|---|---|---|---|---|
| qwen2.5-coder:7b (local baseline) | Ollama default quant, 0 (M2 Metal) | 54.0% | 0.0% | 27.1% | <fill in if known, else "not timed"> |
| Qwen2.5-Coder-32B-Instruct-AWQ (Bridges-2) | AWQ 4-bit, 1x V100-32 | <fill in> | <fill in> | <fill in> | <fill in> |
| Qwen3-Coder-30B-A3B-Instruct (Bridges-2) | fp16, 2x V100-32 | <fill in> | <fill in> | <fill in> | <fill in> |

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

Read the existing entries first (e.g. the 2026-09-11 entries from Phase 4's final review) to match voice/structure exactly — Context / Options / Decision / Consequence. Append (do not overwrite existing content):

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

Find the Phase 5 line (currently `- [ ] **Phase 5 — Scale-out evals.** Larger model comparison on GPU infrastructure, expanded gold set.`) and check it off with the real one-line finding, matching the exact style already used for Phases 1-4's roadmap lines. Note this is only the model-comparison half of Phase 5 — the master prompt's full Phase 5 acceptance criteria also requires ≥50 new reviewed gold cases via log-mining, planned separately as "Phase 5 part 2." Phrase the roadmap line to reflect that this is a completed sub-part, not full Phase 5 completion, unless the human partner has decided otherwise by this point.

- [ ] **Step 5: Run the full local test suite one more time**

Run: `uv run pytest -q`
Expected: all tests still passing (this task touched no `ledgerql/` code beyond Task 1's already-committed and tested `llm_backends.py`; only docs/reports/gitignore change here — run it anyway rather than assume).

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

(This plan works directly on `main`, not a feature branch — confirmed explicitly with the human partner before Task 1 started. Every task's changes are either a small, tested, isolated application-code addition (Task 1) or docs/scripts/reports, and each commit is independently safe to have on `main` even mid-plan.)
