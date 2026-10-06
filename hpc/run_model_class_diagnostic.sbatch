#!/usr/bin/env bash
#SBATCH --job-name=model_class_diagnostic
#SBATCH --account=disease_ecology
#SBATCH --partition=gpu-a100
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --array=1-40%4
#SBATCH --output=/project/disease_ecology/STGNN-output/model_class_diagnostic/logs/array-%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/model_class_diagnostic/logs/array-%A_%a.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/model-class-diagnostic
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
mkdir -p /project/disease_ecology/STGNN-output/model_class_diagnostic/logs
python scripts/run_model_class_diagnostic.py \
  --mode run \
  --output-root /project/disease_ecology/STGNN-output/model_class_diagnostic \
  --prior-root /project/disease_ecology/STGNN-output/stgnn_a3_ablation \
  --structured-metrics /project/disease_ecology/STGNN-output/predictor_augmentation/fold_metrics.csv \
  --task-index "${SLURM_ARRAY_TASK_ID}"
