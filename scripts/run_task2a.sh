#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repository_root}"
: "${STGNN_OUTPUT_ROOT:?set STGNN_OUTPUT_ROOT}"
: "${STGNN_ENVIRONMENTAL_ROOT:?set STGNN_ENVIRONMENTAL_ROOT}"
: "${STGNN_TEMPLATE_PATH:?set STGNN_TEMPLATE_PATH}"
: "${STGNN_PYTHON_ENV:?set STGNN_PYTHON_ENV}"

mkdir -p "${STGNN_OUTPUT_ROOT}/model_data" "${STGNN_OUTPUT_ROOT}/logs/slurm"
source hpc/env_r.sh
if [[ "${STGNN_SKIP_DATASET_BUILD:-0}" != "1" ]]; then
  Rscript scripts/build_production_dataset.R \
    --output-root "${STGNN_OUTPUT_ROOT}" \
    --environment-root "${STGNN_ENVIRONMENTAL_ROOT}" \
    --template "${STGNN_TEMPLATE_PATH}" \
    --analysis-start 2024-01-01 \
    --analysis-end 2026-07-19 \
    --history-weeks 52
fi

source hpc/env_python.sh
git_sha="$(git rev-parse HEAD)"
python python/task2a_pipeline.py \
  --output-root "${STGNN_OUTPUT_ROOT}" \
  --task1-manifest "${STGNN_OUTPUT_ROOT}/manifests/preflight_manifest.json" \
  --git-sha "${git_sha}"
