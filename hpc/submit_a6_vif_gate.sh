#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_VIF_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-vif-bounded-gate}"
RUN_ID="${A6_VIF_RUN_ID:-fold3_seed31415_$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ROOT="${A6_VIF_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_vif_bounded_gate/run_${RUN_ID}}"
ORIGINAL_ROOT="${A6_VIF_ORIGINAL_RUN_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_full_e734427_retry5d_20261106}"

if [[ "${RUN_ROOT}" != /90daydata/disease_ecology/* ]]; then
  echo "A6_VIF_STORAGE_BLOCKED: output must be under /90daydata/disease_ecology" >&2
  exit 2
fi
if [[ -e "${RUN_ROOT}" ]]; then
  echo "A6_VIF_ONE_SHOT_BLOCKED: output root already exists; automatic retries are disabled: ${RUN_ROOT}" >&2
  exit 3
fi
mkdir -p "${RUN_ROOT}/logs"

sbatch --parsable \
  --job-name=stgnn_a6vif_f3_s31415 \
  --cpus-per-task=16 --mem=64G --time=06:00:00 --no-requeue \
  --output="${RUN_ROOT}/logs/slurm-%j.out" \
  --error="${RUN_ROOT}/logs/slurm-%j.err" \
  --export="ALL,STGNN_A6_VIF_REPOSITORY_ROOT=${REPO_ROOT},A6_VIF_OUTPUT_ROOT=${RUN_ROOT},A6_VIF_DURABLE_SUMMARY_ROOT=${REPO_ROOT}/analysis/a6_vif_bounded_gate/results,A6_VIF_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_vif.sbatch"
