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
# Task 2A must be run into refresh_root before this job; previous_root is read-only input.
refresh_root="${STGNN_REFRESH_ROOT:-/project/disease_ecology/STGNN-output/refresh_2026-10-17}"
source_root="${STGNN_SOURCE_OUTPUT_ROOT:-${refresh_root}}"
previous_root="${STGNN_PREVIOUS_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output}"
observation_path="${STGNN_OBSERVATION_PATH:-/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-10-17.csv}"
mkdir -p "${refresh_root}/logs"
source hpc/env_r.sh
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-feature/2026-10-production-refresh}"
export STGNN_GIT_SHA="$(git rev-parse HEAD)"
refresh_args=(
  --source-output-root "${source_root}"
  --previous-output-root "${previous_root}"
  --model-output "${refresh_root}/revised_model_data"
  --observation-path "${observation_path}"
  --boundary-path /project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg
  --boundary-layer study_states
  --analysis-start "${STGNN_ANALYSIS_START:-2024-01-01}"
  --response-start "${STGNN_RESPONSE_START:-2025-W01}"
  --task2d-commit "${STGNN_TASK2D_COMMIT:-e18777f1d98c539c92acc9ba1e7e4deb84b54319}"
  --git-sha "${STGNN_GIT_SHA}"
)
if [[ -n "${STGNN_ANALYSIS_END:-}" ]]; then
  refresh_args+=(--analysis-end "${STGNN_ANALYSIS_END}")
fi
if [[ -n "${STGNN_RESPONSE_END:-}" ]]; then
  refresh_args+=(--response-end "${STGNN_RESPONSE_END}")
fi
Rscript scripts/run_task2e_refresh.R "${refresh_args[@]}"
