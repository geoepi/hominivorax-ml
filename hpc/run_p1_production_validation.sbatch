#!/usr/bin/env bash
# Exact-frozen-artifact P1 validation.  Protected inputs remain on Atlas and
# machine-readable summaries are written to the checked-out P1 worktree.
#SBATCH --job-name=stgnn-p1-validation
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p1_production_validation/logs/p1-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p1_production_validation/logs/p1-%j.err

set -euo pipefail

REPO="${P1_REPO:-/project/disease_ecology/STGNN-output/worktrees/p1-production-validation}"
cd "${REPO}"
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

mkdir -p /project/disease_ecology/STGNN-output/p1_production_validation/logs

python analysis/p1_production_validation/scripts/run_p1_validation.py \
  --repository-root "${REPO}" \
  --output-root "${REPO}/analysis/p1_production_validation" \
  --prediction-archive /project/disease_ecology/STGNN-output/prospective_evaluation_refresh_2026-10-17/a3-prospective-corrected-20261017/predictions/prospective_predictions.parquet \
  --refresh-dynamic /project/disease_ecology/STGNN-output/refresh_2026-10-17/revised_model_data/raw/dynamic_features.npy \
  --refresh-static /project/disease_ecology/STGNN-output/refresh_2026-10-17/revised_model_data/raw/static_features.npy \
  --refresh-weeks /project/disease_ecology/STGNN-output/refresh_2026-10-17/revised_model_data/raw/weeks.parquet \
  --refresh-calendar /project/disease_ecology/STGNN-output/refresh_2026-10-17/revised_model_data/raw/calendar_features.parquet \
  --refresh-front /project/disease_ecology/STGNN-output/refresh_2026-10-17/v2_model/front_features/causal_front_features.parquet \
  --development-counts /project/disease_ecology/STGNN-output/revised_model_data/raw/targets_count.npy \
  --development-weeks /project/disease_ecology/STGNN-output/revised_model_data/raw/weeks.parquet \
  --road-night /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --bootstrap-replicates 399

