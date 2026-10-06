#!/usr/bin/env bash
#SBATCH --job-name=stgnn-predictor-augmentation-fit
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --array=2-4,6-8,10-12,14-16%4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_%A_%a.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export AUGMENTATION_ARRAY_CONCURRENCY=4
python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py worker \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --task-id "$SLURM_ARRAY_TASK_ID"

