#!/usr/bin/env bash
#SBATCH --job-name=neural_a0_audit
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --array=1-40%4
#SBATCH --output=/project/disease_ecology/STGNN-output/neural_a0_architecture_audit/logs/array-%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/neural_a0_architecture_audit/logs/array-%A_%a.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/neural-a0-architecture-audit
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
mkdir -p /project/disease_ecology/STGNN-output/neural_a0_architecture_audit/logs

python scripts/run_neural_a0_architecture_audit.py \
  --mode run \
  --output-root /project/disease_ecology/STGNN-output/neural_a0_architecture_audit \
  --task-index "${SLURM_ARRAY_TASK_ID}"
