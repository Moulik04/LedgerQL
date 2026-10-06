#!/bin/bash
#SBATCH --job-name=ledgerql-gen-32b-awq
#SBATCH --partition=GPU-shared
#SBATCH --gres=gpu:h100-80:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=%x_%j.out
#SBATCH --error=%x_%j.err

# Task 9 bake-off, generation-only (evals/gen_only_eval.py): ANSWER-expected
# cases, N=5 candidates each, no classify/answer stage, then guard/execute/vote.
# Qwen2.5-Coder-32B AWQ 4-bit: the earlier 32B, needed for the pairwise-agreement table.
# Runs a 3-case smoke test on the first profile before the full sweep (see
# run_model_eval.sh); submit with SMOKE_ONLY=1 exported to stop after it.
# H100-80 (docs/bridges2.md), native BF16 weights, TP=1. If vllm dies on a
# KV-cache ValueError, resubmit with --gres=gpu:h100-80:2 and a tensor-parallel
# size of 2 on the last line.
set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
export EVAL_MODE=gen_only
export PROFILES="current xiyan omnisql"
# Set, not inherited: a value left exported in the submitting shell would add linked runs.
export ENTITY_LINK_AB=""
# Context length, explicit: the longest prompt over all 103 cases and 3 profiles is
# 2253 tokens (omnisql, measured with these models' tokenizers), plus 2048 generated
# tokens (evals/gen_only_eval.py DEFAULT_MAX_TOKENS) = 4301; 5120 leaves headroom.
# One 5120-token sequence is 1.25 GiB of KV cache on the 32B (64 layers x 8 KV heads
# x 128 x 2 x 2 bytes = 256 KiB/token) against ~9-10 GiB free at 0.95 utilisation.
# The 256K default is what overflowed the cache before (docs/bridges2.md).
export MAX_MODEL_LEN=5120
export VLLM_EXTRA_ARGS="--gpu-memory-utilization 0.95"
# The commit of the model's repository to download: main as it has stood since before the first
# cluster run (2026-09-14), so the weights every earlier run of this job was served.
export MODEL_REVISION=1ed0a6145da0ce550c628e8e8b678f51e695995d
bash scripts/bridges2/run_model_eval.sh Qwen/Qwen2.5-Coder-32B-Instruct-AWQ 1
