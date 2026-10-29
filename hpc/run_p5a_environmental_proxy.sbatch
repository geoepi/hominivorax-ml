#!/usr/bin/env bash
#SBATCH --job-name=stgnn-p5a-proxy
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p5a_environmental_proxy_20261029/logs/p5a-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p5a_environmental_proxy_20261029/logs/p5a-%j.err

set -euo pipefail

REPO="${P5A_REPO:?P5A_REPO must point to the isolated P5A worktree}"
ROOT="${P5A_OUTPUT_ROOT:?P5A_OUTPUT_ROOT must identify the isolated P5A output root}"
MODEL_OUTPUT="${P5A_MODEL_OUTPUT:?P5A_MODEL_OUTPUT must identify the validated refresh model output}"
P2_ROOT="${P5A_P2_ROOT:?P5A_P2_ROOT must identify the immutable P2 output root}"
P4_ROOT="${P5A_P4_ROOT:?P5A_P4_ROOT must identify the immutable P4 output root}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

SCRIPT="${REPO}/analysis/p5a_environmental_proxy/scripts/run_p5a_environmental_proxy.py"
COMMON=(--repository-root "${REPO}" --output-root "${ROOT}" --model-output "${MODEL_OUTPUT}" --p2-output-root "${P2_ROOT}" --p4-root "${P4_ROOT}")

python "${SCRIPT}" --mode all "${COMMON[@]}"
python "${REPO}/analysis/p5a_environmental_proxy/scripts/render_p5a_figures.py" --output-root "${ROOT}"
python "${REPO}/analysis/p5a_environmental_proxy/scripts/render_p5a_report.py" --repository-root "${REPO}" --output-root "${ROOT}"
