#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --time=08:00:00
#SBATCH --job-name=stgnn-task2a
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.err

set -euo pipefail
source hpc/env_r.sh
source hpc/env_python.sh
export STGNN_OUTPUT_ROOT="${STGNN_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output}"
export STGNN_ENVIRONMENTAL_ROOT="${STGNN_ENVIRONMENTAL_ROOT:?set STGNN_ENVIRONMENTAL_ROOT}"
export STGNN_TEMPLATE_PATH="${STGNN_TEMPLATE_PATH:?set STGNN_TEMPLATE_PATH}"
export STGNN_JOB_IDS="${STGNN_JOB_IDS:-${SLURM_JOB_ID:-}}"
source scripts/run_task2a.sh
