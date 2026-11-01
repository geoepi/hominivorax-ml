#!/usr/bin/env bash
#SBATCH --job-name=stgnn_a5_gnn
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/logs/a5_gnn_%j.out
#SBATCH --error=/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/logs/a5_gnn_%j.err

set -euo pipefail
REPO_ROOT="${STGNN_A5_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"
cd "${REPO_ROOT}"
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export A5_GNN_OUTPUT_ROOT="${A5_GNN_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_${SLURM_JOB_ID}_${STGNN_GIT_SHA:0:7}}"
export A5_GNN_CACHE_ROOT="${A5_GNN_CACHE_ROOT:-${A5_GNN_OUTPUT_ROOT}/cache}"
export A5_GNN_TMP_ROOT="${A5_GNN_TMP_ROOT:-${A5_GNN_OUTPUT_ROOT}/tmp}"
export A5_GNN_DURABLE_SUMMARY_ROOT="${A5_GNN_DURABLE_SUMMARY_ROOT:-${REPO_ROOT}/analysis/a5_gnn_bounded_comparison}"
export XDG_CACHE_HOME="${A5_GNN_CACHE_ROOT}/xdg"
export TORCH_HOME="${A5_GNN_CACHE_ROOT}/torch"
export TMPDIR="${A5_GNN_TMP_ROOT}"
mkdir -p "${A5_GNN_OUTPUT_ROOT}" "${A5_GNN_CACHE_ROOT}" "${A5_GNN_TMP_ROOT}" "${XDG_CACHE_HOME}" "${TORCH_HOME}" "${A5_GNN_DURABLE_SUMMARY_ROOT}/results" "${A5_GNN_DURABLE_SUMMARY_ROOT}/provenance" "${A5_GNN_DURABLE_SUMMARY_ROOT}/figures"
df -h /project/disease_ecology
df -h /90daydata/disease_ecology

python analysis/a5_gnn_bounded_comparison/scripts/run_a5_gnn.py \
  --config analysis/a5_gnn_bounded_comparison/config/a5_gnn_config.json \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --edges /project/disease_ecology/STGNN-output/revised_model_data/raw/edges_queen.parquet \
  --a3-reference analysis/structured_a3_final_comparison/results/fold_metrics.csv \
  --a3-frozen-output /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --spatial-assignments /project/disease_ecology/STGNN-output/revised_model_data/splits/spatial_node_assignments.parquet \
  --output-root "${A5_GNN_OUTPUT_ROOT}" \
  --durable-summary-root "${A5_GNN_DURABLE_SUMMARY_ROOT}" \
  --device cuda
