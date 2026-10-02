#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --time=00:30:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.err

set -euo pipefail
source hpc/env_r.sh

: "${STGNN_OBSERVATIONS:?set STGNN_OBSERVATIONS}"
: "${STGNN_ENVIRONMENTAL_ROOT:?set STGNN_ENVIRONMENTAL_ROOT}"
: "${STGNN_LIVESTOCK_ROOT:?set STGNN_LIVESTOCK_ROOT}"
: "${STGNN_TEMPLATE_PATH:?set STGNN_TEMPLATE_PATH}"
: "${STGNN_PYTHON_ENV:?set STGNN_PYTHON_ENV}"

source scripts/run_cpu_preflight.sh
