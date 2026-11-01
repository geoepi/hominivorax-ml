#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A5B_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
RUN_ID="${A5B_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_${STGNN_GIT_SHA:0:7}}"
RUN_ROOT="${A5B_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_${RUN_ID}}"
mkdir -p "${RUN_ROOT}/checkpoints" "${RUN_ROOT}/predictions" "${RUN_ROOT}/tensors" "${RUN_ROOT}/residuals" "${RUN_ROOT}/tmp" "${RUN_ROOT}/cache" "${RUN_ROOT}/figures_work" "${RUN_ROOT}/logs" "${RUN_ROOT}/manifests"
{
  echo "run_id=${RUN_ID}"
  echo "execution_sha=${STGNN_GIT_SHA}"
  echo "repository_root=${REPO_ROOT}"
  echo "output_root=${RUN_ROOT}"
  df -h /project/disease_ecology
  df -h /90daydata/disease_ecology
} > "${RUN_ROOT}/manifests/storage_preflight.txt"

sbatch \
  --export="ALL,STGNN_A5B_REPOSITORY_ROOT=${REPO_ROOT},STGNN_GIT_SHA=${STGNN_GIT_SHA},STGNN_GIT_BRANCH=${STGNN_GIT_BRANCH},A5B_OUTPUT_ROOT=${RUN_ROOT},A5B_CACHE_ROOT=${RUN_ROOT}/cache,A5B_TMP_ROOT=${RUN_ROOT}/tmp,A5B_DURABLE_SUMMARY_ROOT=${REPO_ROOT}/analysis/a5b_multiscale_component_spatial_ml,A5B_FROZEN_A3_OUTPUT=/project/disease_ecology/STGNN-output/structured_a3_final_comparison,A5B_A4S_FROZEN_OUTPUT=/project/disease_ecology/STGNN-output/a4s_challenger_freeze_2026-10-17,A5B_A5_REFERENCE_ROOT=${REPO_ROOT}/analysis/a5_gnn_bounded_comparison" \
  --output="${RUN_ROOT}/logs/%x-%j.out" \
  --error="${RUN_ROOT}/logs/%x-%j.err" \
  hpc/run_a5b_multiscale_component_spatial_ml.sbatch
