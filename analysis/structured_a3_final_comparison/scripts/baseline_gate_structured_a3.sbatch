#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-gate
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/structured_a3_gate_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/structured_a3_gate_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/structured-a3-final-comparison
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/structured_a3_final_comparison/scripts/run_structured_a3_final.py baseline \
  --output-root /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv
