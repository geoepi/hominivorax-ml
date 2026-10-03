#!/usr/bin/env bash
#SBATCH --job-name=stgnn-task2g-score
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task2g_score_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task2g_score_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export MKL_NUM_THREADS=${SLURM_CPUS_PER_TASK}

python scripts/run_task2g_terminal.py \
  --phase score \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --terminal-output /project/disease_ecology/STGNN-output/terminal_evaluation
