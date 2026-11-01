#!/usr/bin/env bash
#SBATCH --job-name=stgnn_a6_gpb
#SBATCH --account=disease_ecology
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/logs/a6_%j.out
#SBATCH --error=/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/logs/a6_%j.err

set -euo pipefail
REPO_ROOT="${STGNN_A6_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export A6_PYTHON_ENV="${A6_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
if [[ ! -f "${A6_PYTHON_ENV}/bin/activate" ]]; then
  echo "A6_SOFTWARE_DEPENDENCY_BLOCKED: missing isolated GPBoost environment ${A6_PYTHON_ENV}" >&2
  exit 20
fi
source "${A6_PYTHON_ENV}/bin/activate"
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export A6_OUTPUT_ROOT="${A6_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_${SLURM_JOB_ID}_${STGNN_GIT_SHA:0:7}}"
export A6_TMP_ROOT="${A6_TMP_ROOT:-${A6_OUTPUT_ROOT}/tmp}"
export A6_CACHE_ROOT="${A6_CACHE_ROOT:-${A6_OUTPUT_ROOT}/gp_cache}"
export TMPDIR="${A6_TMP_ROOT}"
export XDG_CACHE_HOME="${A6_CACHE_ROOT}/xdg"
mkdir -p "${A6_OUTPUT_ROOT}" "${A6_TMP_ROOT}" "${A6_CACHE_ROOT}" "${XDG_CACHE_HOME}" "${A6_OUTPUT_ROOT}/logs" "${A6_OUTPUT_ROOT}/results" "${A6_OUTPUT_ROOT}/provenance" "${A6_OUTPUT_ROOT}/figures"
df -h /project/disease_ecology
df -h /90daydata/disease_ecology

python analysis/a6_gpboost_correlated_spatial_ml/scripts/run_a6.py \
  --config analysis/a6_gpboost_correlated_spatial_ml/config/a6_config.json \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --edges /project/disease_ecology/STGNN-output/revised_model_data/raw/edges_queen.parquet \
  --a3-reference analysis/structured_a3_final_comparison/results/fold_metrics.csv \
  --a3-frozen-output /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --a4s-frozen-output /project/disease_ecology/STGNN-output/a4s_challenger_freeze_2026-10-17 \
  --a5b-reference-root analysis/a5b_multiscale_component_spatial_ml \
  --spatial-assignments /project/disease_ecology/STGNN-output/revised_model_data/splits/spatial_node_assignments.parquet \
  --output-root "${A6_OUTPUT_ROOT}" \
  --durable-summary-root analysis/a6_gpboost_correlated_spatial_ml
