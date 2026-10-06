#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-fullfit
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/fullfit_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/fullfit_%j.err

set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
cd "${repo_root}"
output_root=/project/disease_ecology/STGNN-output/structured_a3_fullfit
mkdir -p "${output_root}/logs"

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
python analysis/structured_a3_fullfit/scripts/run_fullfit_products.py fit \
  --output-root "${output_root}" \
  --permutation-replicates 10

module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 intel-oneapi-mkl/2023.2.0 r/4.4.3
export R_LIBS_USER=/project/disease_ecology/STGNN-r-lib:/home/john.humphreys/R/x86_64-pc-linux-gnu-library/4.4
Rscript --vanilla analysis/structured_a3_fullfit/scripts/render_fullfit_spatial.R \
  --output-root "${output_root}" \
  --mask /project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
python analysis/structured_a3_fullfit/scripts/run_fullfit_products.py finalize \
  --output-root "${output_root}"
