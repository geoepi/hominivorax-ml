#!/usr/bin/env bash
#SBATCH --job-name=stgnn_task2e_baselines
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task2e_baselines_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task2e_baselines_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
mkdir -p /project/disease_ecology/STGNN-output/logs
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
python scripts/run_task2e_baselines.py \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data
