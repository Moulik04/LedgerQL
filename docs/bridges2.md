# PSC Bridges-2

Populated in Phase 5, when scale-out evals and the strong-model comparison
move to Bridges-2 V100s. Will cover: module/environment setup, SLURM batch
submission (`scripts/bridges2/*.sbatch`), fp16-only constraints (no
bfloat16, no FlashAttention-2), and allocation-hour budgeting.

Per the checkpoint rule in the master prompt: **stop and ask MJ before
anything that touches Bridges-2** — allocation hours are finite.
