#!/bin/bash
#SBATCH --job-name=ledgerql-eval-30b
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:v100-32:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
bash scripts/bridges2/run_model_eval.sh Qwen/Qwen3-Coder-30B-A3B-Instruct 2
