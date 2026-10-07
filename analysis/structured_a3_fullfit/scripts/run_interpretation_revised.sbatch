#!/usr/bin/env bash
#SBATCH --job-name=stgnn-a3-visuals
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=04:00:00
#SBATCH --chdir=/project/disease_ecology/STGNN-output/worktrees/a3-interpretation-visuals
#SBATCH --output=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/interpretation_revised_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/interpretation_revised_%j.err

set -euo pipefail
repo_root=/project/disease_ecology/STGNN-output/worktrees/a3-interpretation-visuals
output_root=/project/disease_ecology/STGNN-output/structured_a3_fullfit
cd "${repo_root}"

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
python analysis/structured_a3_fullfit/scripts/build_effect_reference_profile.py \
  --output-root "${output_root}" \
  --output "${output_root}/interpretation_revised/effects/effect_response_reference_profile.csv"

module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 intel-oneapi-mkl/2023.2.0 r/4.4.3
export R_LIBS_USER=/project/disease_ecology/STGNN-r-lib:/home/john.humphreys/R/x86_64-pc-linux-gnu-library/4.4
Rscript --vanilla analysis/structured_a3_fullfit/scripts/render_interpretation_revised.R \
  --output-root "${output_root}" \
  --mask /project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif
