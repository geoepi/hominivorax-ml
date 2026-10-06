#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-finalize
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/structured_a3_finalize_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/structured_a3_finalize_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/structured-a3-final-comparison
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/structured_a3_final_comparison/scripts/finalize_structured_a3_final.py \
  --output-root /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --atlas-job-ids "FIT_A0=${STRUCTURED_A3_A0_JOB_ID:-unknown},GATE=${STRUCTURED_A3_GATE_JOB_ID:-unknown},FIT_A3=${STRUCTURED_A3_A3_JOB_ID:-unknown}"
