#!/usr/bin/env bash
# One restartable W44 origin fit, with h=1,2,3 and E0/E1/realized comparison.
#SBATCH --job-name=stgnn-w44-q1-origin
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --array=0-25%8
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/w44-q1-origin-%A_%a.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/w44-q1-origin-%A_%a.err

set -euo pipefail

REPO="/project/disease_ecology/STGNN-output/worktrees/structured-a3-2026w44-q1-retrospective"
CANDIDATE_ROOT="/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44"
OUTPUT_ROOT="/project/disease_ecology/STGNN-output/structured_a3_2026w44_q1_retrospective"
OBSERVATION_SOURCE="/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-11-13.csv"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

python "${REPO}/analysis/structured_a3_data_refresh_2026w44/qualification_execution/run_w44_q1_retrospective.py" \
  --mode origin \
  --repository-root "${REPO}" \
  --candidate-root "${CANDIDATE_ROOT}" \
  --output-root "${OUTPUT_ROOT}" \
  --observation-source "${OBSERVATION_SOURCE}" \
  --origin-slot "${SLURM_ARRAY_TASK_ID}"
