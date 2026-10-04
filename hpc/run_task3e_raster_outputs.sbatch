#!/usr/bin/env bash
# CPU-only Task 3E raster and continuous cell-map production.
# Submit from /project/disease_ecology/STGNN on Atlas.
#SBATCH --job-name=stgnn-task3e-raster
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/v2_rasters/logs/task3e_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/v2_rasters/logs/task3e_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
mkdir -p /project/disease_ecology/STGNN-output/v2_rasters/logs

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
python scripts/task3e_prepare_inputs.py

module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 intel-oneapi-mkl/2023.2.0 r/4.4.3
Rscript --vanilla scripts/task3e_raster_outputs.R
