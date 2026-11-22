#!/usr/bin/env bash
#SBATCH --job-name=stgnn_task2e_refresh
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task2e_refresh_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task2e_refresh_%j.err

set -euo pipefail
repo_root="${STGNN_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${repo_root}"
python3 scripts/w44_execution_preflight.py check-env --mode task2e

# Task 2A must be run into source_root before this job; previous_root is read-only input.
refresh_root="${STGNN_REFRESH_ROOT:?set STGNN_REFRESH_ROOT to the intended output root}"
source_root="${STGNN_SOURCE_OUTPUT_ROOT:?set STGNN_SOURCE_OUTPUT_ROOT to the selected Task 2A bundle}"
previous_root="${STGNN_PREVIOUS_OUTPUT_ROOT:?set STGNN_PREVIOUS_OUTPUT_ROOT to the read-only Task 2D root}"
observation_path="${STGNN_OBSERVATION_PATH:?set STGNN_OBSERVATION_PATH to the selected observation CSV}"
boundary_path="${STGNN_BOUNDARY_PATH:?set STGNN_BOUNDARY_PATH to the selected boundary source}"
boundary_layer="${STGNN_BOUNDARY_LAYER:-study_states}"
expected_observation_sha256="${STGNN_EXPECTED_OBSERVATION_SHA256:?set STGNN_EXPECTED_OBSERVATION_SHA256}"
expected_feature_manifest_sha256="${STGNN_EXPECTED_FEATURE_MANIFEST_SHA256:?set STGNN_EXPECTED_FEATURE_MANIFEST_SHA256}"
analysis_start="${STGNN_ANALYSIS_START:-2024-01-01}"
analysis_end="${STGNN_ANALYSIS_END:-}"
response_start="${STGNN_RESPONSE_START:-2025-W01}"
response_end="${STGNN_RESPONSE_END:-}"
task2d_commit="${STGNN_TASK2D_COMMIT:-e18777f1d98c539c92acc9ba1e7e4deb84b54319}"

preflight_args=(
  task2e --refresh-root "${refresh_root}"
  --source-output-root "${source_root}"
  --previous-output-root "${previous_root}"
  --observation-path "${observation_path}"
  --boundary-path "${boundary_path}"
  --boundary-layer "${boundary_layer}"
  --analysis-start "${analysis_start}"
  --response-start "${response_start}"
  --task2d-commit "${task2d_commit}"
  --expected-observation-sha256 "${expected_observation_sha256}"
  --expected-feature-manifest-sha256 "${expected_feature_manifest_sha256}"
)
if [[ -n "${analysis_end}" ]]; then preflight_args+=(--analysis-end "${analysis_end}"); fi
if [[ -n "${response_end}" ]]; then preflight_args+=(--response-end "${response_end}"); fi
python3 scripts/w44_execution_preflight.py "${preflight_args[@]}"

source hpc/env_r.sh
export STGNN_GIT_SHA="$(git rev-parse HEAD)"
export STGNN_GIT_BRANCH="$(git branch --show-current)"
refresh_args=(
  --source-output-root "${source_root}"
  --previous-output-root "${previous_root}"
  --model-output "${refresh_root}/revised_model_data"
  --observation-path "${observation_path}"
  --expected-observation-sha256 "${expected_observation_sha256}"
  --expected-feature-manifest-sha256 "${expected_feature_manifest_sha256}"
  --boundary-path "${boundary_path}"
  --boundary-layer "${boundary_layer}"
  --analysis-start "${analysis_start}"
  --response-start "${response_start}"
  --task2d-commit "${task2d_commit}"
  --git-sha "${STGNN_GIT_SHA}"
)
if [[ -n "${analysis_end}" ]]; then
  refresh_args+=(--analysis-end "${analysis_end}")
fi
if [[ -n "${response_end}" ]]; then
  refresh_args+=(--response-end "${response_end}")
fi
Rscript scripts/run_task2e_refresh.R "${refresh_args[@]}"
