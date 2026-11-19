#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-fullfit
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --chdir=/project/disease_ecology/STGNN-output/worktrees/structured-a3-fullfit-products
#SBATCH --output=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/fullfit_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/structured_a3_fullfit/logs/fullfit_%j.err

set -euo pipefail
repo_root="${SLURM_SUBMIT_DIR:-/project/disease_ecology/STGNN-output/worktrees/structured-a3-fullfit-products}"
cd "${repo_root}"
output_root="${STGNN_FULLFIT_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output/structured_a3_fullfit}"
model_output="${STGNN_MODEL_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output/revised_model_data}"
front_feature_root="${STGNN_FRONT_FEATURE_ROOT:-/project/disease_ecology/STGNN-output/v2_model/front_features}"
front_features="${STGNN_FRONT_FEATURES:-${front_feature_root}/causal_front_features.parquet}"
anthropogenic_features="${STGNN_ANTHROPOGENIC_FEATURES:-/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet}"
soil_features="${STGNN_SOIL_FEATURES:-/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet}"
response_start="${STGNN_RESPONSE_START:-2025-W01}"
response_end="${STGNN_RESPONSE_END:-}"
mkdir -p "${output_root}/logs"

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
if [[ "${STGNN_BUILD_A3_FRONT_FEATURES:-0}" == "1" ]]; then
  front_args=(--model-output "${model_output}" --output "${front_feature_root}" --response-start "${response_start}")
  if [[ -n "${response_end}" ]]; then
    front_args+=(--response-end "${response_end}")
  fi
  python scripts/build_a3_front_features.py "${front_args[@]}"
fi
python analysis/structured_a3_fullfit/scripts/run_fullfit_products.py fit \
  --output-root "${output_root}" \
  --model-output "${model_output}" \
  --front-features "${front_features}" \
  --anthropogenic-features "${anthropogenic_features}" \
  --soil-features "${soil_features}" \
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
