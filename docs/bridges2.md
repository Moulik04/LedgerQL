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

**Corrected after a real failure, not assumed:** `$HOME` (`/jet`) is
**not** "effectively unconstrained." A real `uv pip install vllm`
failed with `Disk quota exceeded`; `lfs quota -p <projid> /jet`
confirmed a hard **25GiB project quota** on this allocation (the ~347T
figure the sibling project's docs cited is the whole filesystem's
total size, not a per-project cap, and that project's own vllm/torch-
equivalent workload never happened to get big enough to hit this).
`/ocean/projects/cis260102p/mjain10/` is separately confirmed at only
10GB. Neither fits the two model checkpoints (~20GB AWQ + ~60GB fp16,
~80GB combined).

**Resolved via a real capability check, not a workaround:** a live
`srun` allocation on a real H100 node (`w008`) confirmed compute nodes
*do* have outbound internet (`curl -sI https://huggingface.co` and
`https://pypi.org` both returned `HTTP/2 200`), and `$LOCAL`
(node-local NVMe scratch) showed 28T total / 24T free on that node.
So:

- vLLM's own venv (`$HOME/ledgerql-bridges2/vllm-env/.venv`, ~10GB)
  and the LedgerQL repo/venv live under `$HOME/ledgerql-bridges2/` as
  originally planned -- comfortably inside the 25GiB quota by
  themselves.
- **Model checkpoints are NOT pre-downloaded to `$HOME` at all.**
  `run_model_eval.sh` sets `HF_HOME=$LOCAL/hf_cache` before starting
  `vllm serve`, so each job downloads its own checkpoint fresh into
  that job's node-local scratch -- outside the `$HOME` quota entirely,
  and correctly wiped after the job (each model only needs to be
  fetched once per job, not persisted between submissions).
- vLLM lives in its own venv, entirely separate from the main
  `ledgerql` `.venv` -- `vllm`/`torch` are heavy GPU-specific
  dependencies that must never become part of the base
  `pyproject.toml` the 8GB M2 laptop also installs from. The eval
  process itself runs in the main `ledgerql` venv and only needs
  `httpx` (already a base dependency) to talk to vLLM's OpenAI-
  compatible API over HTTP.

(Unrelated pre-existing clutter on this account -- `~/aml_project` and
`~/.conda`, ~13GB combined, leftovers from a different class, not part
of this task -- was also cleared with the human partner's explicit
confirmation, freeing headroom for the vLLM venv install regardless.)

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
(see the "GPU" section above for the reasoning).

### 2026-09-11/13 — Task 3 continued: walltime, quota failure, and the storage redesign

- `scontrol show partition GPU-shared | grep -i maxtime` → `MaxTime=UNLIMITED`. No walltime ceiling concern for this phase's 2.5-4 hour job budgets.
- `bash scripts/bridges2/setup_env.sh` (login node) hit a real `Disk quota exceeded` (errno 122) partway through `uv pip install vllm`, extracting a bundled `.so` file. Investigated rather than retried blindly: `lfs quota -p 102658 /jet` showed `quota=limit=26214400` KB (exactly 25GiB) against ~24GiB already used -- a real, hard **project quota** on `$HOME`, not the "effectively unconstrained" figure assumed from the sibling project's docs (which describes the filesystem's total size, `347T`, not a per-project cap that project never happened to hit).
- Freed ~13GB by removing unrelated pre-existing clutter (`~/aml_project`, `~/.conda`, confirmed with the human partner as safe to delete) -- helpful, but insufficient on its own: the real blocker is that no combination of cleanup makes a 25GiB quota hold ~80GB of model checkpoints.
- Resolved via a real capability check on an actual H100 allocation (`srun --gres=gpu:h100-80:1`, node `w008`): compute nodes have real outbound internet (`curl` to `huggingface.co`/`pypi.org` both returned `200`), and `$LOCAL` showed `28T` total / `24T` free. Redesigned `setup_env.sh` to stop pre-downloading checkpoints entirely, and `run_model_eval.sh` to set `HF_HOME=$LOCAL/hf_cache` so each job downloads its own model fresh into node-local scratch instead. See the "Storage layout" section above for the corrected design.
- Bumped both `.sbatch` files' `--time` (32B AWQ job: 2h → 2.5h; 30B fp16 job: 3h → 4h) to account for checkpoint download time now happening inside the job itself, not before it.
- Still to confirm: the vLLM + AWQ smoke test itself (server actually starts and answers a real request) on a real H100 allocation, now using the corrected `HF_HOME`-redirected download path.

<!-- Further entries appended by Task 3's remaining step, then Tasks 4-6,
     as real commands are run and real output comes back. -->
