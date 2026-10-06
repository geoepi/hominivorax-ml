#!/usr/bin/env bash
#SBATCH --job-name=stgnn-predictor-augmentation-gate
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_gate_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_gate_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py baseline \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv
