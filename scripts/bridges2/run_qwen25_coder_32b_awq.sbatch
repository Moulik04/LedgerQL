#!/bin/bash
#SBATCH --job-name=ledgerql-eval-32b
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:h100-80:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
bash scripts/bridges2/run_model_eval.sh Qwen/Qwen2.5-Coder-32B-Instruct-AWQ 1
