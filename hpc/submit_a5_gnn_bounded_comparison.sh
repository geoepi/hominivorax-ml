#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A5_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
RUN_ID="${A5_GNN_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)_${STGNN_GIT_SHA:0:7}}"
RUN_ROOT="${A5_GNN_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_${RUN_ID}}"
mkdir -p "${RUN_ROOT}/checkpoints" "${RUN_ROOT}/predictions" "${RUN_ROOT}/training" "${RUN_ROOT}/tmp" "${RUN_ROOT}/cache" "${RUN_ROOT}/figures_work" "${RUN_ROOT}/logs" "${RUN_ROOT}/manifests"
{
  echo "run_id=${RUN_ID}"
  echo "execution_sha=${STGNN_GIT_SHA}"
  echo "repository_root=${REPO_ROOT}"
  echo "output_root=${RUN_ROOT}"
  df -h /project/disease_ecology
  df -h /90daydata/disease_ecology
} > "${RUN_ROOT}/manifests/storage_preflight.txt"

sbatch \
  --export="ALL,STGNN_A5_REPOSITORY_ROOT=${REPO_ROOT},STGNN_GIT_SHA=${STGNN_GIT_SHA},STGNN_GIT_BRANCH=${STGNN_GIT_BRANCH},A5_GNN_OUTPUT_ROOT=${RUN_ROOT},A5_GNN_CACHE_ROOT=${RUN_ROOT}/cache,A5_GNN_TMP_ROOT=${RUN_ROOT}/tmp,A5_GNN_DURABLE_SUMMARY_ROOT=${REPO_ROOT}/analysis/a5_gnn_bounded_comparison" \
  --output="${RUN_ROOT}/logs/%x-%j.out" \
  --error="${RUN_ROOT}/logs/%x-%j.err" \
  hpc/run_a5_gnn_bounded_comparison.sbatch
