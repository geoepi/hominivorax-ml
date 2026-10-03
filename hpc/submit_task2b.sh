#!/usr/bin/env bash
set -euo pipefail
export STGNN_TASK2B_MODE="${STGNN_TASK2B_MODE:-smoke}"
export STGNN_TASK2B_EPOCHS="${STGNN_TASK2B_EPOCHS:-2}"
sbatch --export=ALL hpc/run_task2b.sbatch
