#!/usr/bin/env bash
#SBATCH --job-name=stgnn-a3-cartography
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --chdir=/project/disease_ecology/STGNN-output/worktrees/structured-a3-2026w44-cartographic-v1
#SBATCH --output=/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/logs/cartographic_revision_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/logs/cartographic_revision_%j.err

set -euo pipefail

repo_root="${SLURM_SUBMIT_DIR:-/project/disease_ecology/STGNN-output/worktrees/structured-a3-2026w44-cartographic-v1}"
candidate_root="/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44"
mode="${STGNN_CARTOGRAPHIC_MODE:-full}"
if [[ "${mode}" == "pilot" ]]; then
  output_root="${STGNN_CARTOGRAPHIC_OUTPUT_ROOT:-${candidate_root}/figures_cartographic_revision_v1_pilot}"
else
  output_root="${candidate_root}/figures_cartographic_revision_v1"
fi

cd "${repo_root}"
module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 intel-oneapi-mkl/2023.2.0 r/4.4.3
export R_LIBS_USER=/project/disease_ecology/STGNN-r-lib:/home/john.humphreys/R/x86_64-pc-linux-gnu-library/4.4

Rscript --vanilla analysis/structured_a3_fullfit/scripts/render_cartographic_revision.R \
  --mode "${mode}" \
  --candidate-root "${candidate_root}" \
  --output-root "${output_root}"
