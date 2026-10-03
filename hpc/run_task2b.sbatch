#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=24:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/task2b-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/task2b-%j.err
set -euo pipefail

cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
mkdir -p /project/disease_ecology/STGNN-output/{models/task2b,runs/task2b,validation/task2b,diagnostics/task2b,manifests/task2b,logs/slurm}

MODE="${STGNN_TASK2B_MODE:-smoke}"
EPOCHS="${STGNN_TASK2B_EPOCHS:-2}"
python scripts/run_task2b_experiments.py \
  --repo /project/disease_ecology/STGNN \
  --output-root /project/disease_ecology/STGNN-output \
  --mode "${MODE}" \
  --epochs "${EPOCHS}"
