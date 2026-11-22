#!/usr/bin/env bash
#SBATCH --job-name=a3-point-clustering-w44
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/a3-point-clustering-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/a3-point-clustering-%j.err

set -euo pipefail

REPO="${A3_POINT_REPO:?A3_POINT_REPO must point to the isolated Atlas worktree}"
OUTPUT_ROOT="${A3_POINT_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output/a3_point_spatiotemporal_clustering_w44}"
REPOSITORY_RESULTS="${REPO}/analysis/a3_point_spatiotemporal_clustering/results"
SCRIPT="${REPO}/analysis/a3_point_spatiotemporal_clustering/scripts/run_point_clustering.py"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

python "${SCRIPT}" --mode check --output-root "${OUTPUT_ROOT}"
python "${SCRIPT}" \
  --mode full \
  --workers "${SLURM_CPUS_PER_TASK}" \
  --output-root "${OUTPUT_ROOT}" \
  --repository-results "${REPOSITORY_RESULTS}"
