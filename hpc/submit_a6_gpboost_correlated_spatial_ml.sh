#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export A6_PYTHON_ENV="${A6_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
RUN_ID="${A6_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_${STGNN_GIT_SHA:0:7}}"
RUN_ROOT="${A6_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_${RUN_ID}}"
mkdir -p "${RUN_ROOT}/models" "${RUN_ROOT}/predictions" "${RUN_ROOT}/gp_cache" "${RUN_ROOT}/datasets" "${RUN_ROOT}/residuals" "${RUN_ROOT}/tmp" "${RUN_ROOT}/logs" "${RUN_ROOT}/environment" "${RUN_ROOT}/figures_work" "${RUN_ROOT}/manifests" "${RUN_ROOT}/results" "${RUN_ROOT}/provenance" "${RUN_ROOT}/figures"
{
  echo "run_id=${RUN_ID}"
  echo "execution_sha=${STGNN_GIT_SHA}"
  echo "repository_root=${REPO_ROOT}"
  echo "output_root=${RUN_ROOT}"
  echo "python_environment=${A6_PYTHON_ENV}"
  df -h /project/disease_ecology
  df -h /90daydata/disease_ecology
} > "${RUN_ROOT}/manifests/storage_preflight.txt"

sbatch \
  --export="ALL,STGNN_A6_REPOSITORY_ROOT=${REPO_ROOT},STGNN_GIT_SHA=${STGNN_GIT_SHA},STGNN_GIT_BRANCH=${STGNN_GIT_BRANCH},A6_PYTHON_ENV=${A6_PYTHON_ENV},A6_OUTPUT_ROOT=${RUN_ROOT},A6_TMP_ROOT=${RUN_ROOT}/tmp,A6_CACHE_ROOT=${RUN_ROOT}/gp_cache" \
  --output="${RUN_ROOT}/logs/%x-%j.out" \
  --error="${RUN_ROOT}/logs/%x-%j.err" \
  hpc/run_a6_gpboost_correlated_spatial_ml.sbatch
