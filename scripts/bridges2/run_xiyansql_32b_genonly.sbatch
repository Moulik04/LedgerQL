#!/bin/bash
#SBATCH --job-name=ledgerql-gen-xiyan-32b
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:h100-80:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

# Task 9 bake-off, generation-only (evals/gen_only_eval.py): ANSWER-expected
# cases, N=5 candidates each, no classify/answer stage, then guard/execute/vote.
# XiYanSQL-QwenCoder-32B-2504, BF16 (~65.5GB), Apache-2.0, ungated; native profile = M-Schema.
# Runs a 3-case smoke test on the first profile before the full sweep (see
# run_model_eval.sh); submit with SMOKE_ONLY=1 exported to stop after it.
# H100-80 (docs/bridges2.md), native BF16 weights, TP=1. If vllm dies on a
# KV-cache ValueError, resubmit with --gres=gpu:h100-80:2 and a tensor-parallel
# size of 2 on the last line.
set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
export EVAL_MODE=gen_only
export PROFILES="xiyan current omnisql"
export VLLM_EXTRA_ARGS="--gpu-memory-utilization 0.95"
bash scripts/bridges2/run_model_eval.sh XGenerationLab/XiYanSQL-QwenCoder-32B-2504 1
