#!/usr/bin/env bash
#SBATCH --job-name=stgnn-p5-operational-contract
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p5_operational_contract_20261029/logs/p5-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p5_operational_contract_20261029/logs/p5-%j.err

set -euo pipefail

REPO="${P5_REPO:?P5_REPO must point to the isolated P5 worktree}"
ROOT="${P5_OUTPUT_ROOT:?P5_OUTPUT_ROOT must identify the isolated P5 output root}"
MODEL_OUTPUT="${P5_MODEL_OUTPUT:?P5_MODEL_OUTPUT must identify the validated refresh model output}"
FRONT_FEATURES="${P5_FRONT_FEATURES:?P5_FRONT_FEATURES must identify causal front features}"
ROAD_NIGHT="${P5_ROAD_NIGHT:?P5_ROAD_NIGHT must identify node-static anthropogenic features}"
SOIL="${P5_SOIL:?P5_SOIL must identify node-static soil features}"
P4_ROOT="${P5_P4_ROOT:?P5_P4_ROOT must identify the immutable P4 output root}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

SCRIPT="${REPO}/analysis/p5_operational_contract/scripts/run_p5_operational_contract.py"
COMMON=(--issue-week 2026-W36 --horizons 1,2,3 --model-output "${MODEL_OUTPUT}" --front-features "${FRONT_FEATURES}" --road-night "${ROAD_NIGHT}" --soil "${SOIL}" --p4-root "${P4_ROOT}")

python "${SCRIPT}" --mode dry-run --run-id p5-preflight-20261029 --output-root "${ROOT}/preflight" "${COMMON[@]}"
python "${SCRIPT}" --mode replay --run-id p5-replay-a-20261029 --output-root "${ROOT}/replay_a" "${COMMON[@]}"
python "${SCRIPT}" --mode replay --run-id p5-replay-b-20261029 --output-root "${ROOT}/replay_b" "${COMMON[@]}"
python "${REPO}/analysis/p5_operational_contract/scripts/compare_p5_replays.py" --first "${ROOT}/replay_a" --second "${ROOT}/replay_b" --output "${ROOT}/reproducibility_comparison"
python "${REPO}/analysis/p5_operational_contract/scripts/run_p5_failure_tests.py" --output "${ROOT}/failure_tests"
python "${REPO}/analysis/p5_operational_contract/scripts/render_p5_report.py" --repository-root "${REPO}" --output-root "${ROOT}" --job-id "${SLURM_JOB_ID}"
