#!/bin/bash
#SBATCH --job-name=ledgerql-eval-32b
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:h100-80:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:30:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
# Every variable the job body reads with a default is set here, so the run does not depend on
# what the submitting shell happened to export (submit.sh passes that whole environment on).
# These are the job body's own defaults, so a run submitted from a clean shell is unchanged. Left
# to the submission: GOLD_FILE and SMOKE_ONLY. LEDGERQL_ENTITY_LINK is checked by the run itself.
export EVAL_MODE=pipeline
export PROFILES=""
export ENTITY_LINK_AB=""
export MAX_MODEL_LEN=8192
export VLLM_EXTRA_ARGS=""
bash scripts/bridges2/run_model_eval.sh Qwen/Qwen2.5-Coder-32B-Instruct-AWQ 1
