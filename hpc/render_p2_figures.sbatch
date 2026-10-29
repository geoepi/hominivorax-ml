#!/usr/bin/env bash
# Render the bounded P2 figure set from compact summaries.
#SBATCH --job-name=stgnn-p2-figures
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/logs/figures-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/logs/figures-%j.err

set -euo pipefail
REPO="${P2_REPO:?P2_REPO must point to the isolated Atlas worktree}"
Rscript "${REPO}/analysis/p2_operational_nowcast/scripts/render_p2_figures.R" \
  "${REPO}/analysis/p2_operational_nowcast/results" \
  "${REPO}/analysis/p2_operational_nowcast/figures"
