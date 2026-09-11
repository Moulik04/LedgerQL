# Phase 5 (part 1): remote model comparison on PSC Bridges-2 — design spec

## Goal

Answer one empirical question: does a larger open-weight local model meaningfully improve
LedgerQL's real numbers (execution accuracy, hallucinated-number rate, abstain precision) over
the `qwen2.5-coder:7b` baseline this project has used through Phases 2-4, given the same
guardrails/self-consistency/verifier pipeline unchanged?

This directly informs whether Phase 6 (LoRA fine-tuning, per `LEDGERQL_MASTER_PROMPT.md`) is
worth pursuing at all: if a much bigger pretrained model barely moves the numbers, the bottleneck
is probably not raw model capability (ambiguous schema, genuinely hard queries, self-consistency
disagreement) and a small fine-tuned model trained on a handful of examples is unlikely to fix
that either.

## Non-goals

- **Not fine-tuning.** No training happens in this phase. See `LEDGERQL_MASTER_PROMPT.md` Phase
  6 and the 2026-09-11 conversation record for why: the only labeled data this project has is
  `evals/gold.jsonl` (103 cases), which is two orders of magnitude too small to fine-tune
  anything without overfitting, and training on it would destroy its value as the untouched eval
  set every other phase's numbers depend on.
- **Not a production/live-pipeline change.** The default model for the live pipeline stays
  `qwen2.5-coder:7b` on local Ollama. This phase produces a comparison report, not a config
  change. Whether to adopt a bigger model permanently is a decision for after the real numbers
  are in, and would need its own follow-up (a bigger model needs a standing place to run — this
  phase deliberately does not solve that).
- **Minimal, isolated `ledgerql/` changes only.** The master prompt explicitly prefers vLLM (or
  `transformers`+`peft`) over Ollama for Bridges-2 serving — confirmed by re-reading
  `LEDGERQL_MASTER_PROMPT.md` §3, missed in this spec's first draft. `generate.py`, `answer.py`,
  and `classify.py` all inject an optional `client` duck-typed to `ollama.Client`'s own
  `.generate(model, system, prompt, options) -> obj.response` shape — confirmed by reading all
  three. The only change needed is a single new module, `ledgerql/llm_backends.py`, providing
  `default_client()` (returns `ollama.Client` or a new `VLLMClient` based on an `LLM_BACKEND` env
  var) and `VLLMClient` itself (a pure-`httpx` adapter matching the same duck-typed shape — no
  `vllm`/`torch` install needed client-side, only on the Bridges-2 *server*). The three modules'
  own logic, and every existing test that injects a fake client directly, are untouched.
- **Not a persistent remote-inference service.** Each comparison run is a single bounded SLURM
  job that starts Ollama, runs the eval, and ends. No tunnel, no long-running server the laptop
  depends on.

## Model candidates

Two, served via vLLM from their real HuggingFace repos (`vllm serve <repo-id>`), each at a
precision level chosen to actually fit the available hardware without a documented reliability
risk:

1. **`Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`** — the *official* Qwen-published 4-bit AWQ quant
   (~20GB), fits a single V100-32GB with room for KV cache. Same model family as the existing
   `qwen2.5-coder:7b` baseline, just larger — isolates "does scale help" as close to a single
   variable as possible, since this project's prompts were empirically tuned against the 7B's
   specific behavior. Dense architecture, no tensor-parallel complications.
2. **`Qwen/Qwen3-Coder-30B-A3B-Instruct`** — run at **full fp16, no quantization**, across
   **2× V100-32GB via vLLM tensor parallelism** (`--tensor-parallel-size 2`). The only available
   AWQ quant for this model is third-party (not from Qwen) and carries an explicit upstream
   warning ("suffers significant loss under 4-bit quantization, please use with caution"), plus a
   `--enable-expert-parallel` requirement that effectively forces 2 GPUs anyway for its MoE expert
   tensors to divide evenly. Given 2 GPUs are needed regardless, running at full fp16 avoids the
   quantization-loss confound entirely — a bad result then means "the model," not "the quant."

## Hardware

- `Qwen2.5-Coder-32B-Instruct-AWQ`: `--gres=gpu:v100-32:1` on `GPU-shared` — a real, already-
  working resource string for this account (`mjain10` / `cis260102p`) from the user's other
  project's sbatch jobs. L40S-48 nodes also exist on this partition (confirmed via `sinfo` in
  that project) but have never actually been used in a submitted job on this account; V100-32 is
  reused here for the same reason, not because L40S is worse.
- `Qwen3-Coder-30B-A3B-Instruct` (fp16): `--gres=gpu:v100-32:2`, same node (single-node tensor
  parallelism — cross-node would need extra coordination this phase doesn't need). ~60GB of fp16
  weights across 64GB of combined GPU memory is tight but should fit; Task 3's verification step
  confirms `GPU-shared` actually permits a 2-GPU request for this account before Task 5 depends
  on it (some shared partitions cap per-job GPU count below what a node physically has).

## Architecture: run entirely on the compute node, no tunnel

The Bridges-2 GPU node has no route back to this laptop, and this laptop has no SSH key
registered with PSC (password-only auth, confirmed — a non-interactive `ssh` attempt returned
`Permission denied`). Rather than solve that, the whole comparison runs on Bridges-2 itself:

1. LedgerQL's repo (public on GitHub) is cloned onto Bridges-2.
2. `data/ledgerql.duckdb` (gitignored, ~194MB) is copied over separately via `scp`, run by the
   user from this laptop (same reason as above — outbound `scp` needs the same password auth).
3. vLLM is installed in a **separate, Bridges-2-only Python environment** (not the main
   `ledgerql` `.venv` / `pyproject.toml` — `vllm`+`torch`+CUDA are heavy, GPU-specific
   dependencies that must never become a required install for the 8GB M2 laptop). Model weights
   are pre-downloaded via `huggingface-cli download` on the login node.
4. One SLURM job per model (not both in one job) — simpler to reason about against an unverified
   walltime limit, and a failure in the second model's run can't invalidate the first's already-
   captured results. Each job: starts `vllm serve <repo-id> --port 8000 [--tensor-parallel-size N
   for the 2-GPU model]`, health-checks it via vLLM's OpenAI-compatible `/health` endpoint, then
   runs `LLM_BACKEND=vllm OLLAMA_MODEL=<repo-id> make eval` (in the main `ledgerql` `.venv`, which
   only needs `httpx` — already a base dependency — to talk to vLLM) against the copied DB and the
   existing `evals/gold.jsonl`, then copies the report files to model-tagged names with `:`/`/`
   sanitized to `-` for filesystem/scp safety (`reports/eval_bridges2_qwen2.5-coder-32b-awq.md` /
   `..._<date>.jsonl`, same pattern for the second model) so the second run doesn't clobber the
   first.
5. The user `scp`s the tagged report files back to this laptop.

**Model download and Python dependency install happen on the login node, before any `sbatch`
submission** — not inside the GPU job. This sidesteps an unverified risk (whether Bridges-2
compute nodes even have outbound internet to `huggingface.co`/PyPI; login nodes generally do). By
the time a GPU job runs, the weights and both Python environments already exist locally and just
need to be read — matching the existing `setup_env.sh` precedent in the user's other project,
which does exactly this for the same reason.

## Open questions this plan resolves via verification, not assumption

Following this project's own established pattern (verify the real thing, don't assume it from
docs) and its precedent in the sibling Bridges-2 doc ("everything below is verified against the
real cluster, not assumed from generic docs"), the implementation plan's early steps are
verification gates, not code:

1. **Does vLLM actually install and serve on Bridges-2's login/compute nodes** (CUDA/driver
   version compatibility, whether the AWQ quant kernel is supported on V100's Volta architecture —
   AWQ support varies by GPU compute capability, not assumed compatible without a real smoke
   test)? Smoke-tested before anything else.
2. **Does `GPU-shared` actually permit a 2-GPU request for this account** — needed for the
   `qwen3-coder` fp16 run; the sibling project's precedent only ever requested 1 GPU.
3. **Current `GPU-shared` walltime limit and real queue wait**, via `scontrol show partition
   GPU-shared` and `squeue` — the sibling project's V100 job used 3 hours for a training run;
   this phase's workload is pure inference (~103 cases × ~6 LLM calls each × 2 models), likely
   faster, but not assumed faster without a real timed run.
4. **SU cost of a real run** — checked against the ~481/500 SU balance after the first model
   completes, before submitting the second (the 2-GPU fp16 run costs roughly double the SU rate
   of the 1-GPU AWQ run, on top of it likely taking longer per-token at fp16 vs. 4-bit).

## Reporting

Results get folded into a short Phase 5 comparison write-up (not a full new `reports/eval.md`
generator change — this is a one-off comparison, reusing the existing report format's numbers
directly): a table of `qwen2.5-coder:7b` (existing baseline) vs. `qwen2.5-coder:32b` vs.
`qwen3-coder:30b` on execution accuracy / hallucinated-number rate / abstain precision / wall
time per run. Before accepting any surprising number (e.g., a large accuracy jump or an
unexpected regression), spot-check real per-case records the same way Phase 4's Task 7 did —
different inference backend (CUDA L40S/V100 vs. this laptop's Metal) is a new variable that
hasn't been exercised before in this project.

A `DECISIONS.md` entry records whichever conclusion the real numbers support (adopt a bigger
model for a future default-model decision, or stay on `qwen2.5-coder:7b` because the delta didn't
justify the operational cost of a bigger model) — matching this project's established practice of
documenting a real finding whether or not it's the outcome that was hoped for.

## Acceptance criteria

- Real (not assumed) execution accuracy / hallucinated-number rate / abstain precision numbers
  for at least one larger model, from an actual `make eval` run against the unmodified
  `evals/gold.jsonl`, on real Bridges-2 hardware.
- A clear, evidence-based recommendation: is a bigger model worth pursuing further (and if so,
  which), or does the evidence point elsewhere (e.g., toward Phase 6's fine-tuning path, or
  toward neither and back to the pipeline's own structural limits).
- The only `ledgerql/` change is the new `llm_backends.py` module and its own tests; every
  existing test and call site is untouched (verified by running the full local suite unchanged).
  Zero change to the live pipeline's default model or default backend (`LLM_BACKEND` defaults to
  `ollama`).
