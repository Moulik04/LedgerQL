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
(`mjain10` / `cis260102p`) and hardware pool (V100-32 on `GPU-shared`)
are the same. That project's V100 job was training a deep model, not
serving vLLM for inference -- worth re-confirming independently.

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

## GPU

- `Qwen2.5-Coder-32B-Instruct-AWQ`: `--gres=gpu:v100-32:1` on
  `GPU-shared` -- reuses the sibling project's already-working
  resource string for this exact account.
- `Qwen3-Coder-30B-A3B-Instruct` (full fp16, no quantization --
  the only available AWQ quant is third-party and carries an explicit
  upstream quality-loss warning, plus effectively requires 2 GPUs
  anyway for its MoE expert tensors): `--gres=gpu:v100-32:2`, single
  node, `vllm serve --tensor-parallel-size 2`. Not yet confirmed that
  `GPU-shared` permits a 2-GPU request for this account -- see the
  design spec's Open Questions; Task 3 verifies this before Task 5
  depends on it.

See the design spec's "Hardware" section for the full reasoning on
both.

## Status

<!-- Filled in by Tasks 3-6 as real commands are run and real output
     comes back. Do not write speculative numbers here. -->
