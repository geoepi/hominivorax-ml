#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_OPT_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-opt-efficient}"
RUN_ROOT="${A6_OPT_OUTPUT_ROOT:?set A6_OPT_OUTPUT_ROOT to the existing gate run root}"
ORIGINAL_ROOT="${A6_OPT_ORIGINAL_RUN_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_full_e734427_retry5d_20261106}"

mkdir -p "${RUN_ROOT}/logs"
JOB_ID="$(sbatch --parsable \
  --job-name=stgnn_a6o_gate_compare \
  --cpus-per-task=4 --mem=32G --time=12:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-gate-compare-%j.out" \
  --error="${RUN_ROOT}/logs/a6opt-gate-compare-%j.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=gate-compare,A6_OPT_FOLD=3,A6_OPT_SEED=31415,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch")"
echo "Submitted comparison-only gate completion ${JOB_ID} for ${RUN_ROOT}"
