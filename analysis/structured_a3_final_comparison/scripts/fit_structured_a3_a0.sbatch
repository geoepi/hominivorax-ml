#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-a0
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --array=1,3,5,7%4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/structured_a3_a0_%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/structured_a3_a0_%A_%a.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/structured-a3-final-comparison
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/structured_a3_final_comparison/scripts/run_structured_a3_final.py worker \
  --output-root /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --task-id "${SLURM_ARRAY_TASK_ID}"
