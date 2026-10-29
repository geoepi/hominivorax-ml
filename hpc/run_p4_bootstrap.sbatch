#!/usr/bin/env bash
# One restartable temporal-week bootstrap replicate per array task.
#SBATCH --job-name=stgnn-p4-bootstrap
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --array=0-119%16
#SBATCH --output=/project/disease_ecology/STGNN-output/p4_uncertainty_extrapolation_20261029/logs/bootstrap-%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p4_uncertainty_extrapolation_20261029/logs/bootstrap-%A_%a.err

set -euo pipefail

REPO="${P4_REPO:?P4_REPO must point to the isolated Atlas worktree}"
OUTPUT_ROOT="${P4_OUTPUT_ROOT:?P4_OUTPUT_ROOT must identify the isolated P4 output root}"
P2_OUTPUT_ROOT="${P4_P2_OUTPUT_ROOT:?P4_P2_OUTPUT_ROOT must identify the immutable P2 output root}"
MODEL_OUTPUT="${P4_MODEL_OUTPUT:?P4_MODEL_OUTPUT must identify the validated refresh model output}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

python "${REPO}/analysis/p4_uncertainty_extrapolation/scripts/run_p4_uncertainty_extrapolation.py" \
  --mode bootstrap \
  --repository-root "${REPO}" \
  --p2-output-root "${P2_OUTPUT_ROOT}" \
  --model-output "${MODEL_OUTPUT}" \
  --output-root "${OUTPUT_ROOT}" \
  --replicate-id "${SLURM_ARRAY_TASK_ID}"
