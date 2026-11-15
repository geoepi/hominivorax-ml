#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=atlas
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=06:00:00
#SBATCH --signal=B:USR1@1800
#SBATCH --no-requeue

set -euo pipefail

JOB_SCRIPT_STARTED="$(date +%s)"
REPO_ROOT="${STGNN_A6_VIF_REPOSITORY_ROOT:-/project/disease_ecology/STGNN-output/_WORKTREES/a6-vif-bounded-gate}"
cd "${REPO_ROOT}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export A6_VIF_PYTHON_ENV="${A6_VIF_PYTHON_ENV:-/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/gpboost_env_1.8.0}"
if [[ ! -f "${A6_VIF_PYTHON_ENV}/bin/activate" ]]; then
  echo "A6_VIF_SOFTWARE_BLOCKED: expected GPBoost 1.8.0 environment ${A6_VIF_PYTHON_ENV}" >&2
  exit 20
fi
source "${A6_VIF_PYTHON_ENV}/bin/activate"

export STGNN_GIT_SHA="${STGNN_GIT_SHA:-$(git rev-parse HEAD)}"
export STGNN_GIT_BRANCH="${STGNN_GIT_BRANCH:-$(git branch --show-current)}"
export SLURM_CPUS_PER_TASK="${SLURM_CPUS_PER_TASK:?Slurm CPU allocation is missing}"
if [[ "${SLURM_CPUS_PER_TASK}" != "16" ]]; then
  echo "A6_VIF_RESOURCE_BLOCKED: expected 16 CPUs, got ${SLURM_CPUS_PER_TASK}" >&2
  exit 21
fi

export OMP_NUM_THREADS=16
export OMP_THREAD_LIMIT=16
export OMP_DYNAMIC=FALSE
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export BLIS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

export A6_VIF_OUTPUT_ROOT="${A6_VIF_OUTPUT_ROOT:?A6_VIF_OUTPUT_ROOT must be a unique path under /90daydata}"
export A6_VIF_DURABLE_SUMMARY_ROOT="${A6_VIF_DURABLE_SUMMARY_ROOT:-${REPO_ROOT}/analysis/a6_vif_bounded_gate/results}"
export A6_VIF_TMP_ROOT="${A6_VIF_TMP_ROOT:-${A6_VIF_OUTPUT_ROOT}/tmp}"
export A6_VIF_CACHE_ROOT="${A6_VIF_CACHE_ROOT:-${A6_VIF_OUTPUT_ROOT}/cache}"
export TMPDIR="${A6_VIF_TMP_ROOT}"
export XDG_CACHE_HOME="${A6_VIF_CACHE_ROOT}/xdg"
mkdir -p "${A6_VIF_OUTPUT_ROOT}/logs" "${A6_VIF_TMP_ROOT}" "${A6_VIF_CACHE_ROOT}" "${XDG_CACHE_HOME}" "${A6_VIF_OUTPUT_ROOT}/results" "${A6_VIF_OUTPUT_ROOT}/provenance"

OUTPUT_ROOT="${A6_VIF_OUTPUT_ROOT}"
RUNNER_PID=""
STOP_REASON=""
BUDGET_EXCEEDED=0
HARD_DEADLINE=$((JOB_SCRIPT_STARTED + 20100)) # 05:35:00 after Slurm job start

write_supervisor_event() {
  local event="$1"
  local temporary="${OUTPUT_ROOT}/logs/.supervisor_status.$$.tmp"
  printf '{"utc":"%s","event":"%s","job_id":"%s","reason":"%s"}\n' "$(date -u +%FT%TZ)" "${event}" "${SLURM_JOB_ID:-unknown}" "${STOP_REASON}" > "${temporary}"
  mv -f "${temporary}" "${OUTPUT_ROOT}/logs/supervisor_status.json"
}

handle_pre_timeout() {
  STOP_REASON="Slurm pre-timeout signal received; runner was asked to stop at a safe Python boundary"
  write_supervisor_event "SLURM_PRE_TIMEOUT_SIGNAL"
  if [[ -n "${RUNNER_PID}" ]]; then
    kill -USR1 "${RUNNER_PID}" 2>/dev/null || true
  fi
}
trap handle_pre_timeout USR1

RUNNER_ARGS=(
  --mode gate
  --config analysis/a6_vif_bounded_gate/config/a6_vif_config.json
  --model-output /project/disease_ecology/STGNN-output/revised_model_data
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet
  --edges /project/disease_ecology/STGNN-output/revised_model_data/raw/edges_queen.parquet
  --a3-reference analysis/structured_a3_final_comparison/results/fold_metrics.csv
  --a3-frozen-output /project/disease_ecology/STGNN-output/structured_a3_final_comparison
  --original-a6-run-root "${A6_VIF_ORIGINAL_RUN_ROOT:?set A6_VIF_ORIGINAL_RUN_ROOT}"
  --output-root "${OUTPUT_ROOT}"
  --durable-summary-root "${A6_VIF_DURABLE_SUMMARY_ROOT}"
  --fold 3
  --seeds 31415
)

write_supervisor_event "RUNNER_STARTED"
python -u analysis/a6_vif_bounded_gate/scripts/run_a6_vif.py "${RUNNER_ARGS[@]}" \
  > "${OUTPUT_ROOT}/logs/runner.stdout.log" \
  2> "${OUTPUT_ROOT}/logs/runner.stderr.log" &
RUNNER_PID=$!

while kill -0 "${RUNNER_PID}" 2>/dev/null; do
  now="$(date +%s)"
  if (( now >= HARD_DEADLINE )); then
    BUDGET_EXCEEDED=1
    STOP_REASON="external hard-stop at 05:35:00 job elapsed; native GPBoost calls may not be safely interruptible"
    write_supervisor_event "EXTERNAL_HARD_STOP"
    kill -TERM "${RUNNER_PID}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "${RUNNER_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${RUNNER_PID}" 2>/dev/null; then
      kill -KILL "${RUNNER_PID}" 2>/dev/null || true
    fi
    break
  fi
  sleep 5
done

set +e
wait "${RUNNER_PID}"
RUNNER_EXIT_CODE=$?
set -e

if [[ "${BUDGET_EXCEEDED}" == "0" && "${RUNNER_EXIT_CODE}" -eq 0 && -f "${OUTPUT_ROOT}/results/a6_vif_gate_decision.json" ]]; then
  write_supervisor_event "RUNNER_EXITED"
else
  [[ "${STOP_REASON}" != "" ]] || STOP_REASON="runner exited without a successful bounded gate completion (exit ${RUNNER_EXIT_CODE})"
  write_supervisor_event "RUNNER_INCOMPLETE"
fi

set +e
RUN_NAME="${OUTPUT_ROOT##*/}"
FINALIZER_ARGS=(
  --output-root "${OUTPUT_ROOT}"
  --exit-code "${RUNNER_EXIT_CODE}"
  --reason "${STOP_REASON}"
  --durable-report "${A6_VIF_DURABLE_SUMMARY_ROOT}/${RUN_NAME}/a6_vif_gate_report_${RUN_NAME}.md"
)
if [[ "${BUDGET_EXCEEDED}" == "1" ]]; then
  FINALIZER_ARGS+=(--budget-exceeded)
fi
python analysis/a6_vif_bounded_gate/scripts/finalize_a6_vif_budget.py "${FINALIZER_ARGS[@]}" \
  > "${OUTPUT_ROOT}/logs/finalizer.log" 2>&1
FINALIZER_EXIT_CODE=$?
set -e

if [[ "${FINALIZER_EXIT_CODE}" -ne 0 ]]; then
  echo "A6_VIF_FINALIZER_FAILED: exit ${FINALIZER_EXIT_CODE}" >&2
fi

echo "A6_VIF_RUNNER_EXIT_CODE=${RUNNER_EXIT_CODE} FINALIZER_EXIT_CODE=${FINALIZER_EXIT_CODE} BUDGET_EXCEEDED=${BUDGET_EXCEEDED}"
exit "${RUNNER_EXIT_CODE}"
