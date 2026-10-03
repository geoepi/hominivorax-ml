#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/task2c-audit-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/task2c-audit-%j.err
set -euo pipefail

cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
mkdir -p /project/disease_ecology/STGNN-output/{predictions/task2c,validation/task2c,manifests/task2c,logs/slurm}
python scripts/audit_task2c.py --output-root /project/disease_ecology/STGNN-output --experiment task2b
