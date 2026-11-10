#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${STGNN_A6_OPT_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-opt-efficient}"
RUN_ID="${A6_OPT_RUN_ID:-temporal_$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ROOT="${A6_OPT_OUTPUT_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_opt_efficient/run_${RUN_ID}}"
ORIGINAL_ROOT="${A6_OPT_ORIGINAL_RUN_ROOT:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/run_full_e734427_retry5d_20261106}"
GATE_ROOT="${A6_OPT_GATE_OUTPUT_ROOT:?set A6_OPT_GATE_OUTPUT_ROOT to the completed bounded-gate run root}"

export STGNN_PYTHON_ENV="${STGNN_PYTHON_ENV:-/project/disease_ecology/STGNN-python-venv}"
source "${REPO_ROOT}/hpc/env_python.sh"
export A6_PYTHON_ENV="${A6_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
if [[ ! -f "${A6_PYTHON_ENV}/bin/activate" ]]; then
  echo "A6_OPT_SOFTWARE_BLOCKED: missing GPBoost 1.8.0 environment ${A6_PYTHON_ENV}" >&2
  exit 20
fi
source "${A6_PYTHON_ENV}/bin/activate"
python - "${GATE_ROOT}/results/a6_opt_gate_decision.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    raise SystemExit("A6-OPT bounded-gate decision is missing; primary temporal evaluation is not authorized")
decision = json.loads(path.read_text())
if decision.get("status") not in {"A6_OPT_GATE_SUPPORTED", "A6_OPT_GATE_SUPPORTED_WITH_LIMITATIONS"}:
    raise SystemExit(f"A6-OPT gate did not pass ({decision.get('status')}); primary temporal evaluation will not be submitted")
PY
mkdir -p "${RUN_ROOT}/logs"

FOLD_JOB="$(sbatch --parsable \
  --job-name=stgnn_a6o_fold \
  --array=1-4%1 \
  --cpus-per-task=16 --mem=64G --time=2-00:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-fold-%A_%a.out" \
  --error="${RUN_ROOT}/logs/a6opt-fold-%A_%a.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=fold,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch")"
echo "Submitted fold array ${FOLD_JOB}"

AGG_JOB="$(sbatch --parsable \
  --job-name=stgnn_a6o_aggregate \
  --dependency="afterok:${FOLD_JOB}" \
  --cpus-per-task=8 --mem=32G --time=12:00:00 \
  --output="${RUN_ROOT}/logs/a6opt-aggregate-%j.out" \
  --error="${RUN_ROOT}/logs/a6opt-aggregate-%j.err" \
  --export="ALL,STGNN_A6_OPT_REPOSITORY_ROOT=${REPO_ROOT},A6_OPT_MODE=aggregate,A6_OPT_OUTPUT_ROOT=${RUN_ROOT},A6_OPT_ORIGINAL_RUN_ROOT=${ORIGINAL_ROOT}" \
  "${REPO_ROOT}/hpc/run_a6_opt.sbatch")"
echo "Submitted temporal aggregation ${AGG_JOB} after ${FOLD_JOB}"
