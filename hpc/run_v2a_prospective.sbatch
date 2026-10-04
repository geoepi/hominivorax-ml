#!/usr/bin/env bash
# CPU-only STGNN-Hurdle-V2A delayed prospective nowcast harness.
# Submit with: sbatch --export=ALL,FORECAST_WEEK=2026-W30,MODE=readiness hpc/run_v2a_prospective.sbatch
# Score mode additionally requires OBSERVATION_SOURCE=/path/to/node_assigned.parquet.
# TEST_MODE=1 is reserved for historical sandbox checks and never updates the
# production registry or prospective ledger.
#SBATCH --job-name=stgnn-v2a-prospective
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/v2_prospective/logs/prospective_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/v2_prospective/logs/prospective_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

: "${FORECAST_WEEK:?FORECAST_WEEK is required}"
: "${MODE:?MODE must be readiness, forecast, score, or dry-run}"

args=(--forecast-week "${FORECAST_WEEK}" --mode "${MODE}")
if [[ -n "${OBSERVATION_SOURCE:-}" ]]; then
  args+=(--observation-source "${OBSERVATION_SOURCE}")
fi
if [[ -n "${SOURCE_AVAILABLE_TIMESTAMP_UTC:-}" ]]; then
  args+=(--source-available-timestamp-utc "${SOURCE_AVAILABLE_TIMESTAMP_UTC}")
fi
if [[ -n "${ENVIRONMENT_AVAILABLE_TIMESTAMP_UTC:-}" ]]; then
  args+=(--environment-available-timestamp-utc "${ENVIRONMENT_AVAILABLE_TIMESTAMP_UTC}")
fi
if [[ -n "${ENVIRONMENT_AVAILABILITY_STATUS:-}" ]]; then
  args+=(--environment-availability-status "${ENVIRONMENT_AVAILABILITY_STATUS}")
fi
if [[ -n "${ISSUE_TIMESTAMP_UTC:-}" ]]; then
  args+=(--issue-timestamp-utc "${ISSUE_TIMESTAMP_UTC}")
fi
if [[ -n "${HISTORY_MODE:-}" ]]; then
  args+=(--history-mode "${HISTORY_MODE}")
fi
if [[ -n "${SCORE_VERSION:-}" ]]; then
  args+=(--score-version "${SCORE_VERSION}")
fi
if [[ -n "${OUTCOME_MATURITY:-}" ]]; then
  args+=(--outcome-maturity "${OUTCOME_MATURITY}")
fi
if [[ "${TEST_MODE:-0}" == "1" ]]; then
  args+=(--test-mode)
fi

python scripts/run_v2a_prospective.py "${args[@]}"
