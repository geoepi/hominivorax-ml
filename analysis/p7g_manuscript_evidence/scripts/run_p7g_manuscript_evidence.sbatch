#!/usr/bin/env bash
# P7G bounded manuscript-evidence evaluation.  No model fitting is permitted.
# All paths are supplied by the authorized Atlas launcher.
#SBATCH --job-name=stgnn-p7g-evidence
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p7g_manuscript_evidence_20261030/logs/p7g-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p7g_manuscript_evidence_20261030/logs/p7g-%j.err

set -euo pipefail

REPO="${P7G_REPO:?P7G_REPO must point to the isolated P7G Atlas worktree}"
ROOT="${P7G_OUTPUT_ROOT:?P7G_OUTPUT_ROOT must point to the isolated P7G output root}"
P2_ARCHIVE="${P7G_P2_ARCHIVE:?P7G_P2_ARCHIVE must identify the immutable P2 archive}"
P4_SUPPORT="${P7G_P4_SUPPORT:?P7G_P4_SUPPORT must identify the immutable P4 support archive}"
FEATURE_CACHE="${P7G_FEATURE_CACHE:?P7G_FEATURE_CACHE must identify the immutable P2 feature cache}"
NODES="${P7G_NODES:?P7G_NODES must identify the canonical node table}"
EDGES="${P7G_EDGES:?P7G_EDGES must identify the canonical queen graph}"

export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

mkdir -p "${ROOT}/logs"
python "${REPO}/analysis/p7g_manuscript_evidence/scripts/run_p7g_analysis.py" \
  --repository-root "${REPO}" \
  --p2-archive "${P2_ARCHIVE}" \
  --p4-support "${P4_SUPPORT}" \
  --feature-cache "${FEATURE_CACHE}" \
  --nodes "${NODES}" \
  --edges "${EDGES}" \
  --output-root "${ROOT}/results"
