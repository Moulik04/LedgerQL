# PSC Bridges-2 (Phase 5: remote model comparison)

Runs `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` and `Qwen/Qwen3-Coder-30B-A3B-Instruct`
(served via vLLM, per `LEDGERQL_MASTER_PROMPT.md`'s explicit preference over
Ollama for Bridges-2) through LedgerQL's real 103-case eval (`make eval`) on
Bridges-2 GPU hardware, to compare against the local `qwen2.5-coder:7b`
baseline (54.0% execution accuracy / 0.0% hallucinated-number rate / 27.1%
abstain precision). See
`docs/superpowers/specs/2026-09-11-phase5-remote-model-comparison-design.md`
for the full design and why.

Everything below is filled in with real, verified output as this
phase's tasks run -- nothing here is assumed from the sibling
ReorderPoint project's own `docs/bridges2.md`, even where the account
(`mjain10` / `cis260102p`) is the same. That project only ever used
1x V100-32 for training a deep model, not serving vLLM for inference,
and never checked whether H100 nodes were available on this account's
`GPU-shared` allocation -- worth re-confirming every claim
independently rather than reusing it.

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

- vLLM's own venv, both model checkpoints, and the LedgerQL repo/venv
  all live under `$HOME/ledgerql-bridges2/` (on `/jet`, confirmed
  ~347T free in the sibling project's own exploration -- effectively
  unconstrained).
- **Not** `/ocean/projects/cis260102p/mjain10/` -- that allocation is
  only 10GB total, and the two checkpoints alone (~20GB AWQ + ~60GB
  fp16) would not fit.
- vLLM lives in its own venv (`$HOME/ledgerql-bridges2/vllm-env/.venv`),
  entirely separate from the main `ledgerql` `.venv` -- `vllm`/`torch`
  are heavy GPU-specific dependencies that must never become part of
  the base `pyproject.toml` the 8GB M2 laptop also installs from. The
  eval process itself runs in the main `ledgerql` venv and only needs
  `httpx` (already a base dependency) to talk to vLLM's OpenAI-
  compatible API over HTTP.

## GPU: `--gres=gpu:h100-80:1` for both models

Real `sinfo -N -p GPU-shared -o "%N %G"` output (2026-09-11) showed
`GPU-shared` also has `w001`-`w010` nodes with `gpu:h100-80:8` --
H100s with 80GB VRAM, not just the V100-32/V100-16/L40S-48 pools the
design spec's first draft assumed. This changes the plan for the
better, confirmed before committing to the original V100 design:

- `Qwen2.5-Coder-32B-Instruct-AWQ` (~20GB) fits comfortably on one
  H100-80, same as it would on a V100-32.
- `Qwen3-Coder-30B-A3B-Instruct` at full fp16 (~60GB) fits on **one**
  H100-80 -- eliminating the 2-GPU tensor-parallel setup a V100-32
  pair would have needed (and the unconfirmed "does GPU-shared even
  permit a 2-GPU request for this account" question).
- H100 is Hopper (compute capability 9.0), a much safer bet for AWQ
  quantization kernel support than V100/Volta (7.0) -- the exact risk
  Task 3's smoke test exists to check.

Both jobs are now simple single-GPU requests:
`scripts/bridges2/run_qwen25_coder_32b_awq.sbatch` and
`scripts/bridges2/run_qwen3_coder_30b_fp16.sbatch` both use
`--gres=gpu:h100-80:1`, with `run_model_eval.sh` called with
`tensor-parallel-size=1` for both.

The sibling ReorderPoint project's own V100-32 precedent no longer
applies here directly (that project never checked for H100
availability); its GRES-syntax pattern was still a useful starting
point, but this account's H100 access needed its own confirmation via
the real `sinfo` output above, not assumed from that precedent.

## Status

### 2026-09-11 — Task 3, Step 1a: real `sinfo` output

```
$ sinfo -N -p GPU-shared -o "%N %G"
NODELIST GRES
gl001 gpu:l40s-48:8
gl002 gpu:l40s-48:8
gl003 gpu:l40s-48:8
v002-v024 gpu:v100-32:8   (23 nodes)
v025-v033 gpu:v100-16:8   (9 nodes)
v034 gpu:v100-32:16(S:0-95)
w001-w010 gpu:h100-80:8   (10 nodes)
```

H100-80 nodes exist on this account's `GPU-shared` allocation --
switched both jobs to `--gres=gpu:h100-80:1` on the strength of this
(see the "GPU" section above for the reasoning). Still to confirm in
this task: real walltime ceiling, and the vLLM + AWQ smoke test on an
actual H100 allocation (the smoke-test commands below were written
for a V100 allocation originally -- re-verify the `srun --gres`
line matches `gpu:h100-80:1` when actually run).

<!-- Further entries appended by the rest of Task 3, then Tasks 4-6,
     as real commands are run and real output comes back. -->
