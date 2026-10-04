#!/usr/bin/env bash
#SBATCH --job-name=stgnn-task2g-report
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task2g_report_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task2g_report_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh

python scripts/finish_task2g_terminal.py \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --terminal-output /project/disease_ecology/STGNN-output/terminal_evaluation
