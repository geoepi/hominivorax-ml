#!/usr/bin/env bash
#SBATCH --job-name=stgnn-p1-figures
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=/project/disease_ecology/STGNN-output/p1_production_validation/logs/figures-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/p1_production_validation/logs/figures-%j.err

set -euo pipefail
REPO=/project/disease_ecology/STGNN-output/worktrees/p1-production-validation
cd "${REPO}"
source /project/disease_ecology/STGNN/hpc/env_r.sh
Rscript --vanilla analysis/p1_production_validation/scripts/render_p1_figures.R analysis/p1_production_validation

