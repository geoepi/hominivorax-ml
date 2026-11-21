#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repository_root}"
python3 scripts/w44_execution_preflight.py check-env --mode task2a

STGNN_OUTPUT_ROOT="$(python3 scripts/w44_execution_preflight.py resolve-task2a-output \
  --output-root "${STGNN_OUTPUT_ROOT:-}" \
  --refresh-root "${STGNN_REFRESH_ROOT:-}")"
export STGNN_OUTPUT_ROOT
: "${STGNN_ENVIRONMENTAL_ROOT:?set STGNN_ENVIRONMENTAL_ROOT}"
: "${STGNN_TEMPLATE_PATH:?set STGNN_TEMPLATE_PATH}"
: "${STGNN_PYTHON_ENV:?set STGNN_PYTHON_ENV}"
STGNN_SKIP_DATASET_BUILD="${STGNN_SKIP_DATASET_BUILD:-0}"
if [[ "${STGNN_SKIP_DATASET_BUILD}" != "0" && "${STGNN_SKIP_DATASET_BUILD}" != "1" ]]; then
  echo "STGNN_SKIP_DATASET_BUILD must be 0 or 1." >&2
  exit 2
fi

analysis_start="${STGNN_ANALYSIS_START:-2024-01-01}"
analysis_end="${STGNN_ANALYSIS_END:-}"
task1_manifest="${STGNN_OUTPUT_ROOT}/manifests/preflight_manifest.json"
preflight_args=(
  task2a --output-root "${STGNN_OUTPUT_ROOT}"
  --environment-root "${STGNN_ENVIRONMENTAL_ROOT}"
  --template "${STGNN_TEMPLATE_PATH}"
  --task1-manifest "${task1_manifest}"
  --analysis-start "${analysis_start}"
)
if [[ "${STGNN_SKIP_DATASET_BUILD}" == "1" ]]; then preflight_args+=(--skip-dataset-build); fi
if [[ -n "${analysis_end}" ]]; then preflight_args+=(--analysis-end "${analysis_end}"); fi
python3 scripts/w44_execution_preflight.py "${preflight_args[@]}"

source hpc/env_r.sh
mkdir -p "${STGNN_OUTPUT_ROOT}/logs/slurm"
analysis_end_args=()
if [[ -n "${analysis_end}" ]]; then
  analysis_end_args+=(--analysis-end "${analysis_end}")
fi
if [[ "${STGNN_SKIP_DATASET_BUILD}" != "1" ]]; then
  Rscript scripts/build_production_dataset.R \
    --output-root "${STGNN_OUTPUT_ROOT}" \
    --environment-root "${STGNN_ENVIRONMENTAL_ROOT}" \
    --template "${STGNN_TEMPLATE_PATH}" \
    --analysis-start "${analysis_start}" \
    "${analysis_end_args[@]}" \
    --history-weeks 52
fi

source hpc/env_python.sh
git_sha="$(git rev-parse HEAD)"
python python/task2a_pipeline.py \
  --output-root "${STGNN_OUTPUT_ROOT}" \
  --task1-manifest "${task1_manifest}" \
  --git-sha "${git_sha}"
