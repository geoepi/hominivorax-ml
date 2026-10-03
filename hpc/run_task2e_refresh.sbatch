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
mkdir -p /project/disease_ecology/STGNN-output/logs
source hpc/env_r.sh
export STGNN_GIT_BRANCH="feature/revised-domain-baselines"
export STGNN_GIT_SHA="$(git rev-parse HEAD)"
Rscript scripts/run_task2e_refresh.R \
  --source-output-root /project/disease_ecology/STGNN-output \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --observation-path /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv \
  --boundary-path /project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg \
  --boundary-layer study_states \
  --analysis-start 2024-01-01 \
  --analysis-end 2026-07-19 \
  --response-start 2025-W01 \
  --response-end 2026-W29 \
  --task2d-commit e18777f1d98c539c92acc9ba1e7e4deb84b54319 \
  --git-sha "${STGNN_GIT_SHA}"
