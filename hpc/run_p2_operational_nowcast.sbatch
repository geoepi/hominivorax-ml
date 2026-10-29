#!/usr/bin/env bash
# One independently restartable expanding-window origin per array task.
#SBATCH --job-name=stgnn-p2-origin
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --array=0-20%8
#SBATCH --output=/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/logs/origin-%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/logs/origin-%A_%a.err

set -euo pipefail

REPO="${P2_REPO:?P2_REPO must point to the isolated Atlas worktree}"
OUTPUT_ROOT="${P2_OUTPUT_ROOT:?P2_OUTPUT_ROOT must identify the isolated P2 output root}"
MODEL_OUTPUT="${P2_MODEL_OUTPUT:?P2_MODEL_OUTPUT must identify the validated refresh model output}"
FRONT_FEATURES="${P2_FRONT_FEATURES:?P2_FRONT_FEATURES must identify causal front features}"
ROAD_NIGHT="${P2_ROAD_NIGHT:?P2_ROAD_NIGHT must identify static anthropogenic features}"
SOIL="${P2_SOIL:?P2_SOIL must identify static soil features}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

python "${REPO}/analysis/p2_operational_nowcast/scripts/run_p2_operational_nowcast.py" \
  --mode origin \
  --repository-root "${REPO}" \
  --output-root "${OUTPUT_ROOT}" \
  --model-output "${MODEL_OUTPUT}" \
  --front-features "${FRONT_FEATURES}" \
  --road-night "${ROAD_NIGHT}" \
  --soil "${SOIL}" \
  --origin-index "${SLURM_ARRAY_TASK_ID}"
