#!/usr/bin/env bash
#SBATCH --job-name=stgnn_a5b_ms
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/logs/a5b_%j.out
#SBATCH --error=/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/logs/a5b_%j.err

set -euo pipefail
REPO_ROOT="${STGNN_A5B_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export A5B_OUTPUT_ROOT="${A5B_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_${SLURM_JOB_ID}_${STGNN_GIT_SHA:0:7}}"
export A5B_CACHE_ROOT="${A5B_CACHE_ROOT:-${A5B_OUTPUT_ROOT}/cache}"
export A5B_TMP_ROOT="${A5B_TMP_ROOT:-${A5B_OUTPUT_ROOT}/tmp}"
export A5B_DURABLE_SUMMARY_ROOT="${A5B_DURABLE_SUMMARY_ROOT:-${REPO_ROOT}/analysis/a5b_multiscale_component_spatial_ml}"
export A5B_FROZEN_A3_OUTPUT="${A5B_FROZEN_A3_OUTPUT:-/project/disease_ecology/STGNN-output/structured_a3_final_comparison}"
export A5B_A4S_FROZEN_OUTPUT="${A5B_A4S_FROZEN_OUTPUT:-/project/disease_ecology/STGNN-output/a4s_challenger_freeze_2026-10-17}"
export A5B_A5_REFERENCE_ROOT="${A5B_A5_REFERENCE_ROOT:-${REPO_ROOT}/analysis/a5_gnn_bounded_comparison}"
export XDG_CACHE_HOME="${A5B_CACHE_ROOT}/xdg"
export TORCH_HOME="${A5B_CACHE_ROOT}/torch"
export TMPDIR="${A5B_TMP_ROOT}"
mkdir -p "${A5B_OUTPUT_ROOT}" "${A5B_CACHE_ROOT}" "${A5B_TMP_ROOT}" "${XDG_CACHE_HOME}" "${TORCH_HOME}" "${A5B_OUTPUT_ROOT}/logs" "${A5B_DURABLE_SUMMARY_ROOT}/results" "${A5B_DURABLE_SUMMARY_ROOT}/provenance" "${A5B_DURABLE_SUMMARY_ROOT}/figures"
df -h /project/disease_ecology
df -h /90daydata/disease_ecology

python analysis/a5b_multiscale_component_spatial_ml/scripts/run_a5b.py \
  --config analysis/a5b_multiscale_component_spatial_ml/config/a5b_config.json \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --edges /project/disease_ecology/STGNN-output/revised_model_data/raw/edges_queen.parquet \
  --a3-reference analysis/structured_a3_final_comparison/results/fold_metrics.csv \
  --a3-frozen-output "${A5B_FROZEN_A3_OUTPUT}" \
  --a4s-frozen-output "${A5B_A4S_FROZEN_OUTPUT}" \
  --a5-reference-root "${A5B_A5_REFERENCE_ROOT}" \
  --spatial-assignments /project/disease_ecology/STGNN-output/revised_model_data/splits/spatial_node_assignments.parquet \
  --output-root "${A5B_OUTPUT_ROOT}" \
  --durable-summary-root "${A5B_DURABLE_SUMMARY_ROOT}" \
  --device cuda
