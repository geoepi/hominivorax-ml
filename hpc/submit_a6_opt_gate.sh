#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_OPT_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-opt-efficient}"
RUN_ID="${A6_OPT_RUN_ID:-gate_fold3_seed31415_$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ROOT="${A6_OPT_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_opt_efficient/run_${RUN_ID}}"
ORIGINAL_ROOT="${A6_OPT_ORIGINAL_RUN_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_full_e734427_retry5d_20261106}"
mkdir -p "${RUN_ROOT}/logs"

sbatch --parsable \
  --job-name=stgnn_a6o_gate \
  --cpus-per-task=4 --mem=32G --time=24:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-gate-%j.out" \
  --error="${RUN_ROOT}/logs/a6opt-gate-%j.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=gate,A6_OPT_FOLD=3,A6_OPT_SEED=31415,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch"
