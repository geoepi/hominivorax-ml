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
cd /project/disease_ecology/STGNN
# Task 2A must be run into refresh_root before this job; previous_root is read-only input.
refresh_root="${STGNN_REFRESH_ROOT:-/project/disease_ecology/STGNN-output/refresh_2026-10-17}"
previous_root="${STGNN_PREVIOUS_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output}"
mkdir -p "${refresh_root}/logs"
source hpc/env_r.sh
export STGNN_GIT_BRANCH="feature/2026-10-production-refresh"
export STGNN_GIT_SHA="$(git rev-parse HEAD)"
Rscript scripts/run_task2e_refresh.R \
  --source-output-root "${refresh_root}" \
  --previous-output-root "${previous_root}" \
  --model-output "${refresh_root}/revised_model_data" \
  --observation-path /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-10-17.csv \
  --boundary-path /project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg \
  --boundary-layer study_states \
  --analysis-start 2024-01-01 \
  --response-start 2025-W01 \
  --task2d-commit e18777f1d98c539c92acc9ba1e7e4deb84b54319 \
  --git-sha "${STGNN_GIT_SHA}"
