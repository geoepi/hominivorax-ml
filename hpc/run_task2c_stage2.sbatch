#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100-mig7
#SBATCH --gres=gpu:nvidia_a100_1g.10gb:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=06:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/task2c-stage2-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/task2c-stage2-%j.err
set -euo pipefail

cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
mkdir -p /project/disease_ecology/STGNN-output/{models/task2c,runs/task2c,validation/task2c,manifests/task2c,logs/slurm}
python scripts/run_task2c_experiments.py \
  --output-root /project/disease_ecology/STGNN-output \
  --mode stage2 \
  --objectives "exact_joint_hurdle_nll,balanced_multitask_loss:0.1" \
  --epochs 12
