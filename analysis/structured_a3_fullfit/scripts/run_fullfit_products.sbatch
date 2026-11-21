#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-fullfit
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=08:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/fullfit_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/fullfit_%j.err

set -euo pipefail
repo_root="${STGNN_REPOSITORY_ROOT:-${SLURM_SUBMIT_DIR:-}}"
if [[ -z "${repo_root}" || ! -d "${repo_root}" ]]; then
  echo "Set STGNN_REPOSITORY_ROOT or submit from the repository root." >&2
  exit 2
fi
cd "${repo_root}"
python3 scripts/w44_execution_preflight.py check-env --mode fullfit

output_root="${STGNN_FULLFIT_OUTPUT_ROOT:?set STGNN_FULLFIT_OUTPUT_ROOT explicitly}"
model_output="${STGNN_MODEL_OUTPUT_ROOT:?set STGNN_MODEL_OUTPUT_ROOT to the selected Task 2E output}"
anthropogenic_features="${STGNN_ANTHROPOGENIC_FEATURES:?set STGNN_ANTHROPOGENIC_FEATURES explicitly}"
soil_features="${STGNN_SOIL_FEATURES:?set STGNN_SOIL_FEATURES explicitly}"
mask_path="${STGNN_FULLFIT_MASK:?set STGNN_FULLFIT_MASK explicitly}"
expected_observation_sha256="${STGNN_EXPECTED_OBSERVATION_SHA256:?set STGNN_EXPECTED_OBSERVATION_SHA256}"
response_start="${STGNN_RESPONSE_START:?set STGNN_RESPONSE_START explicitly}"
response_end="${STGNN_RESPONSE_END:?set STGNN_RESPONSE_END explicitly}"
build_front="${STGNN_BUILD_A3_FRONT_FEATURES:-0}"
resume_after_fit="${STGNN_RESUME_AFTER_FIT:-0}"
if [[ "${build_front}" != "0" && "${build_front}" != "1" ]]; then
  echo "STGNN_BUILD_A3_FRONT_FEATURES must be 0 or 1." >&2
  exit 2
fi
if [[ "${resume_after_fit}" != "0" && "${resume_after_fit}" != "1" ]]; then
  echo "STGNN_RESUME_AFTER_FIT must be 0 or 1." >&2
  exit 2
fi

preflight_args=(
  fullfit --output-root "${output_root}"
  --model-output "${model_output}"
  --anthropogenic-features "${anthropogenic_features}"
  --soil-features "${soil_features}"
  --expected-observation-sha256 "${expected_observation_sha256}"
  --response-start "${response_start}"
  --response-end "${response_end}"
  --mask-path "${mask_path}"
)
if [[ "${resume_after_fit}" == "1" ]]; then preflight_args+=(--resume-after-fit); fi
if [[ "${build_front}" == "1" ]]; then
  front_feature_root="${STGNN_FRONT_FEATURE_ROOT:?set STGNN_FRONT_FEATURE_ROOT explicitly}"
  if [[ "${resume_after_fit}" == "1" ]]; then
    echo "Cannot rebuild front features while resuming a completed fit." >&2
    exit 2
  fi
  preflight_args+=(--build-front-features --front-feature-root "${front_feature_root}")
else
  front_features="${STGNN_FRONT_FEATURES:?set STGNN_FRONT_FEATURES explicitly}"
  preflight_args+=(--front-features "${front_features}")
fi
python3 scripts/w44_execution_preflight.py "${preflight_args[@]}"

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
if [[ "${build_front}" == "1" ]]; then
  python scripts/build_a3_front_features.py \
    --model-output "${model_output}" \
    --output "${front_feature_root}" \
    --response-start "${response_start}" \
    --response-end "${response_end}"
  front_features="${front_feature_root}/causal_front_features.parquet"
  preflight_args=(
    fullfit --output-root "${output_root}"
    --model-output "${model_output}"
    --front-features "${front_features}"
    --anthropogenic-features "${anthropogenic_features}"
    --soil-features "${soil_features}"
    --expected-observation-sha256 "${expected_observation_sha256}"
    --response-start "${response_start}"
    --response-end "${response_end}"
    --mask-path "${mask_path}"
  )
  python3 scripts/w44_execution_preflight.py "${preflight_args[@]}"
fi

if [[ "${resume_after_fit}" != "1" ]]; then
  python analysis/structured_a3_fullfit/scripts/run_fullfit_products.py fit \
    --output-root "${output_root}" \
    --model-output "${model_output}" \
    --front-features "${front_features}" \
    --anthropogenic-features "${anthropogenic_features}" \
    --soil-features "${soil_features}" \
    --expected-observation-sha256 "${expected_observation_sha256}" \
    --response-start "${response_start}" \
    --response-end "${response_end}" \
    --permutation-replicates 10
fi

module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 intel-oneapi-mkl/2023.2.0 r/4.4.3
export R_LIBS_USER="${STGNN_R_LIBS_USER:-/project/disease_ecology/STGNN-r-lib:/home/john.humphreys/R/x86_64-pc-linux-gnu-library/4.4}"
Rscript --vanilla analysis/structured_a3_fullfit/scripts/render_fullfit_spatial.R \
  --output-root "${output_root}" \
  --mask "${mask_path}" \
  --resume-after-fit

module load py-torch/2.10.0
source /project/disease_ecology/STGNN-python-venv/bin/activate
python analysis/structured_a3_fullfit/scripts/run_fullfit_products.py finalize \
  --output-root "${output_root}" \
  --model-output "${model_output}" \
  --front-features "${front_features}" \
  --anthropogenic-features "${anthropogenic_features}" \
  --soil-features "${soil_features}" \
  --expected-observation-sha256 "${expected_observation_sha256}" \
  --response-start "${response_start}" \
  --response-end "${response_end}" \
  --mask-path "${mask_path}" \
  --resume-after-fit
