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
- **No code changes to `ledgerql/`.** `OLLAMA_MODEL` is already an env-var override read by
  every module that calls Ollama (`generate.py`, `answer.py`, `classify.py`) — confirmed by
  reading all three. Every script this phase adds is new, standalone tooling under
  `scripts/bridges2/`, mirroring the existing pattern in the user's other project
  (`~/Desktop/DS Project/scripts/bridges2/`).
- **Not a persistent remote-inference service.** Each comparison run is a single bounded SLURM
  job that starts Ollama, runs the eval, and ends. No tunnel, no long-running server the laptop
  depends on.

## Model candidates

Two, both fit comfortably in 32GB of GPU memory (see Hardware below):

1. **`qwen2.5-coder:32b`** (20GB, q4_K_M) — same model family as the existing baseline, just
   larger. Isolates "does scale help" as close to a single variable as possible, since this
   project's prompts (system prompts in `answer.py`/`generate.py`, temperature choices) were
   empirically tuned against `qwen2.5-coder:7b`'s specific behavior.
2. **`qwen3-coder:30b`** (19GB, q4_K_M, MoE — 30B total / 3.3B activated) — a newer generation,
   different architecture, similar footprint. Worth the direct empirical comparison rather than
   assuming "newer is better" for this specific task.

Both are pulled from Ollama's public model registry (`ollama.com/library`).

## Hardware: use `gpu:v100-32:1`, not L40S

Bridges-2's `GPU-shared` partition has both V100-32 and L40S-48 nodes available. **This spec
recommends V100-32**, even though L40S has more headroom, because:

- `docs/bridges2.md` (the user's other project) has a **real, working, already-verified**
  `--gres=gpu:v100-32:1` sbatch job on this exact account (`mjain10` / `cis260102p`). L40S is
  only confirmed to exist via `sinfo` output in that doc — never actually used in a submitted
  job on this account.
- Both candidate models (19-20GB) fit in 32GB with room for KV cache/context at the short
  prompt lengths this eval uses (single financial questions, not repo-scale context) — the
  256K-context headroom L40S/qwen3-coder advertise is not needed here.
- Reusing a proven resource string removes a real failure mode (wrong GRES syntax, a
  partition/allocation permission difference) for no accuracy benefit.

If V100-32 turns out to be unavailable/contended when the user actually submits, falling back to
`gpu:l40s-48:1` is a one-line sbatch change — not a design change.

## Architecture: run entirely on the compute node, no tunnel

The Bridges-2 GPU node has no route back to this laptop, and this laptop has no SSH key
registered with PSC (password-only auth, confirmed — a non-interactive `ssh` attempt returned
`Permission denied`). Rather than solve that, the whole comparison runs on Bridges-2 itself:

1. LedgerQL's repo (public on GitHub) is cloned onto Bridges-2.
2. `data/ledgerql.duckdb` (gitignored, ~194MB) is copied over separately via `scp`, run by the
   user from this laptop (same reason as above — outbound `scp` needs the same password auth).
3. Ollama is installed in user space on Bridges-2 (no root available on shared HPC nodes — the
   standard `curl | sh` installer assumes systemd/root, so this uses Ollama's Linux tarball
   instead, extracted to a user directory, `ollama serve` run as a plain background process
   within the job — no systemd needed).
4. One SLURM job per model (not both in one job) — simpler to reason about against an unverified
   walltime limit, and a failure in the second model's run can't invalidate the first's already-
   captured results. Each job: starts `ollama serve &`, health-checks it, runs
   `OLLAMA_MODEL=<model> make eval` against the copied DB and the existing `evals/gold.jsonl`,
   then copies the report files to model-tagged names with `:` sanitized to `-` for filesystem/
   scp safety (`reports/eval_bridges2_qwen2.5-coder-32b.md` /
   `reports/eval_bridges2_qwen2.5-coder-32b_<date>.jsonl`, same pattern for the second model) so
   the second run doesn't clobber the first.
5. The user `scp`s the tagged report files back to this laptop.

**Model pull and Python dependency install happen on the login node, before any `sbatch`
submission** — not inside the GPU job. This sidesteps an unverified risk (whether Bridges-2
compute nodes even have outbound internet to `ollama.com`/PyPI; login nodes generally do). By
the time a GPU job runs, `ollama pull` and `uv sync` have already completed and just need to read
already-fetched data — matching the existing `setup_env.sh` precedent in the user's other
project, which does exactly this for the same reason.

## Open questions this plan resolves via verification, not assumption

Following this project's own established pattern (verify the real thing, don't assume it from
docs) and its precedent in the sibling Bridges-2 doc ("everything below is verified against the
real cluster, not assumed from generic docs"), the implementation plan's early steps are
verification gates, not code:

1. **Does the Ollama Linux tarball actually run on Bridges-2's login/compute nodes** (CPU
   architecture, glibc version, no-root constraints)? Smoke-tested before anything else.
2. **Current `GPU-shared` walltime limit and real queue wait**, via `scontrol show partition
   GPU-shared` and `squeue` — the sibling project's V100 job used 3 hours for a training run;
   this phase's workload is pure inference (~103 cases × ~6 LLM calls each × 2 models), likely
   faster, but not assumed faster without a real timed run.
3. **SU cost of a real run** — checked against the ~481/500 SU balance after the first model
   completes, before submitting the second.

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
- Zero changes to `ledgerql/`'s application code; zero change to the live pipeline's default
  model.
