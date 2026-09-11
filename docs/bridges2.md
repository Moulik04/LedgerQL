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
