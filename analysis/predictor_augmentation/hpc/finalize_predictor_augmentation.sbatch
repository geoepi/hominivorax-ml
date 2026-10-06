#!/usr/bin/env bash
#SBATCH --job-name=stgnn-predictor-augmentation-finalize
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_finalize_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_finalize_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py baseline \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv
python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py finalize \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --reference-manifest analysis/predictor_augmentation/provenance/fixed_theta_baseline_manifest.json

