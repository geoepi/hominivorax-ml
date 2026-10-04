#!/usr/bin/env bash
#SBATCH --job-name=stgnn-task3b-v2a
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task3b_v2a_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task3b_v2a_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

python scripts/run_task3b_v2a.py \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --audit-output /project/disease_ecology/STGNN-output/v2_audit \
  --output /project/disease_ecology/STGNN-output/v2_model
