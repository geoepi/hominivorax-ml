#!/usr/bin/env bash
#SBATCH --job-name=stgnn-p3-figures
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p3_robustness_20261029/logs/figures-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p3_robustness_20261029/logs/figures-%j.err

set -euo pipefail
REPO="${P3_REPO:?P3_REPO must point to the isolated Atlas worktree}"
source /project/disease_ecology/STGNN/hpc/env_r.sh
Rscript "${REPO}/analysis/p3_robustness/scripts/render_p3_figures.R" \
  "${REPO}/analysis/p3_robustness/results" \
  "${REPO}/analysis/p3_robustness/figures"
