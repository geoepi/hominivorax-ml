#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_OPT_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-opt-efficient}"
RUN_ROOT="${A6_OPT_OUTPUT_ROOT:?set A6_OPT_OUTPUT_ROOT to the completed primary run root}"
ORIGINAL_ROOT="${A6_OPT_ORIGINAL_RUN_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_full_e734427_retry5d_20261106}"
mkdir -p "${RUN_ROOT}/logs"

export STGNN_PYTHON_ENV="${STGNN_PYTHON_ENV:-/project/disease_ecology/STGNN-python-venv}"
source "${REPO_ROOT}/hpc/env_python.sh"
export A6_PYTHON_ENV="${A6_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
if [[ ! -f "${A6_PYTHON_ENV}/bin/activate" ]]; then
  echo "A6_OPT_SOFTWARE_BLOCKED: missing GPBoost 1.8.0 environment ${A6_PYTHON_ENV}" >&2
  exit 20
fi
source "${A6_PYTHON_ENV}/bin/activate"

python - "${RUN_ROOT}/results/a6_opt_decision.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    raise SystemExit("A6-OPT primary decision is missing; spatial stress is not authorized")
decision = json.loads(path.read_text())
if not decision.get("primary_guardrails_passed", False):
    raise SystemExit("A6-OPT primary guardrails failed; spatial stress will not be submitted")
PY

FOLD_COUNT="$(python - "${REPO_ROOT}/analysis/a6_opt_efficient" <<'PY'
import pathlib
import pandas as pd
import sys

root = pathlib.Path(sys.argv[1])
path = pathlib.Path("/project/disease_ecology/STGNN-output/revised_model_data/splits/spatial_node_assignments.parquet")
frame = pd.read_parquet(path)
if "spatial_fold" not in frame or "model_node_id" not in frame:
    raise SystemExit("spatial assignment lacks required columns")
print(frame["spatial_fold"].nunique())
PY
)"
if [[ "${FOLD_COUNT}" -lt 2 ]]; then
  echo "spatial assignment contains fewer than two folds" >&2
  exit 21
fi
ARRAY_END="$((FOLD_COUNT - 1))"

FOLD_JOB="$(sbatch --parsable \
  --job-name=stgnn_a6o_spatial \
  --array="0-${ARRAY_END}%1" \
  --cpus-per-task=16 --mem=64G --time=2-00:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-spatial-%A_%a.out" \
  --error="${RUN_ROOT}/logs/a6opt-spatial-%A_%a.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=spatial-fold,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch")"

AGG_JOB="$(sbatch --parsable \
  --job-name=stgnn_a6o_spatial_aggregate \
  --dependency="afterok:${FOLD_JOB}" \
  --cpus-per-task=8 --mem=32G --time=12:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-spatial-aggregate-%j.out" \
  --error="${RUN_ROOT}/logs/a6opt-spatial-aggregate-%j.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=spatial-aggregate,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch")"

echo "Submitted spatial-stress array ${FOLD_JOB} with ${FOLD_COUNT} folds; aggregation ${AGG_JOB} waits for its success."
