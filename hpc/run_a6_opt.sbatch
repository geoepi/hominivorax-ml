#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=atlas
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=2-00:00:00

set -euo pipefail

REPO_ROOT="${STGNN_A6_OPT_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-opt-efficient}"
cd "${REPO_ROOT}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export A6_PYTHON_ENV="${A6_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
if [[ ! -f "${A6_PYTHON_ENV}/bin/activate" ]]; then
  echo "A6_OPT_SOFTWARE_BLOCKED: missing GPBoost 1.8.0 environment ${A6_PYTHON_ENV}" >&2
  exit 20
fi
source "${A6_PYTHON_ENV}/bin/activate"

export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export A6_OPT_OUTPUT_ROOT="${A6_OPT_OUTPUT_ROOT:?A6_OPT_OUTPUT_ROOT must point under /90daydata}"
export A6_OPT_TMP_ROOT="${A6_OPT_TMP_ROOT:-${A6_OPT_OUTPUT_ROOT}/tmp}"
export A6_OPT_CACHE_ROOT="${A6_OPT_CACHE_ROOT:-${A6_OPT_OUTPUT_ROOT}/cache}"
export TMPDIR="${A6_OPT_TMP_ROOT}"
export XDG_CACHE_HOME="${A6_OPT_CACHE_ROOT}/xdg"
mkdir -p "${A6_OPT_OUTPUT_ROOT}" "${A6_OPT_TMP_ROOT}" "${A6_OPT_CACHE_ROOT}" "${XDG_CACHE_HOME}" "${A6_OPT_OUTPUT_ROOT}/logs"

RUNNER_ARGS=( \
  --mode "${A6_OPT_MODE:?A6_OPT_MODE must be gate, fold, aggregate, spatial-fold, or spatial-aggregate}" \
  --config analysis/a6_opt_efficient/config/a6_opt_config.json \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --edges /project/disease_ecology/STGNN-output/revised_model_data/raw/edges_queen.parquet \
  --a3-reference analysis/structured_a3_final_comparison/results/fold_metrics.csv \
  --a3-frozen-output /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --spatial-assignments /project/disease_ecology/STGNN-output/revised_model_data/splits/spatial_node_assignments.parquet \
  --original-a6-run-root "${A6_OPT_ORIGINAL_RUN_ROOT:?set A6_OPT_ORIGINAL_RUN_ROOT}" \
  --output-root "${A6_OPT_OUTPUT_ROOT}" \
  --durable-summary-root analysis/a6_opt_efficient/results \
)

case "${A6_OPT_MODE}" in
  gate)
    RUNNER_ARGS+=(--fold "${A6_OPT_FOLD:?A6_OPT_FOLD is required in gate mode}" --seeds "${A6_OPT_SEED:?A6_OPT_SEED is required in gate mode}")
    ;;
  fold)
    RUNNER_ARGS+=(--fold "${SLURM_ARRAY_TASK_ID:?fold array requires SLURM_ARRAY_TASK_ID}" --seeds 1729 31415 271828)
    ;;
  aggregate)
    ;;
  spatial-fold)
    RUNNER_ARGS+=(--spatial-fold-index "${SLURM_ARRAY_TASK_ID:?spatial-fold array requires SLURM_ARRAY_TASK_ID}")
    ;;
  spatial-aggregate)
    ;;
esac

python analysis/a6_opt_efficient/scripts/run_a6_opt.py "${RUNNER_ARGS[@]}"
