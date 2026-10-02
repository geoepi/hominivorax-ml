#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repository_root}"

: "${STGNN_OUTPUT_ROOT:?set STGNN_OUTPUT_ROOT}"
: "${STGNN_OBSERVATIONS:?set STGNN_OBSERVATIONS}"
: "${STGNN_ENVIRONMENTAL_ROOT:?set STGNN_ENVIRONMENTAL_ROOT}"
: "${STGNN_LIVESTOCK_ROOT:?set STGNN_LIVESTOCK_ROOT}"
: "${STGNN_TEMPLATE_PATH:?set STGNN_TEMPLATE_PATH to the validated canonical raster}"
: "${STGNN_TEMPLATE_PRODUCT:?set STGNN_TEMPLATE_PRODUCT}"
: "${STGNN_TEMPLATE_WEEK:?set STGNN_TEMPLATE_WEEK, for example 2024-W01}"
: "${STGNN_PYTHON_ENV:?set STGNN_PYTHON_ENV to the validated Python environment}"

mkdir -p "${STGNN_OUTPUT_ROOT}/manifests" "${STGNN_OUTPUT_ROOT}/preflight" "${STGNN_OUTPUT_ROOT}/graph" "${STGNN_OUTPUT_ROOT}/logs/slurm"

environment_json="${STGNN_OUTPUT_ROOT}/preflight/r_environment.json"
observation_json="${STGNN_OUTPUT_ROOT}/preflight/observation_audit.json"
inventory_json="${STGNN_OUTPUT_ROOT}/preflight/raster_inventory.json"
nodes_parquet="${STGNN_OUTPUT_ROOT}/preflight/nodes.parquet"
edges_parquet="${STGNN_OUTPUT_ROOT}/preflight/edges_queen.parquet"
graph_qa_json="${STGNN_OUTPUT_ROOT}/preflight/graph_qa.json"
canonical_json="${STGNN_OUTPUT_ROOT}/preflight/canonical_template_validation.json"
diagnostic_json="${STGNN_OUTPUT_ROOT}/preflight/observation_to_grid.json"
diagnostic_parquet="${STGNN_OUTPUT_ROOT}/preflight/observation_node_week_counts.parquet"
contract_json="${STGNN_OUTPUT_ROOT}/preflight/contract_smoke.json"
manifest_json="${STGNN_OUTPUT_ROOT}/manifests/preflight_manifest.json"

Rscript scripts/atlas_r_environment_report.R --output "${environment_json}"
Rscript scripts/audit_observations.R --input "${STGNN_OBSERVATIONS}" --output "${observation_json}"

candidate_end="$(Rscript --vanilla -e 'x <- jsonlite::read_json(commandArgs(TRUE)[1]); y <- x$candidate_period$candidate_analysis_end; if (!is.null(y) && !is.na(y)) cat(y)' "${observation_json}")"
inventory_args=(
  --weekly-root "${STGNN_ENVIRONMENTAL_ROOT}"
  --livestock-root "${STGNN_LIVESTOCK_ROOT}"
  --output "${inventory_json}"
)
if [[ -n "${candidate_end}" ]]; then
  inventory_args+=(--candidate-end "${candidate_end}")
fi
Rscript scripts/inventory_rasters.R "${inventory_args[@]}"
Rscript scripts/validate_canonical_template.R --template "${STGNN_TEMPLATE_PATH}" --inventory "${inventory_json}" --output "${canonical_json}" --product "${STGNN_TEMPLATE_PRODUCT}" --week "${STGNN_TEMPLATE_WEEK}"

Rscript scripts/build_preflight_grid.R --template "${STGNN_TEMPLATE_PATH}" --nodes "${nodes_parquet}" --edges "${edges_parquet}" --qa-output "${graph_qa_json}"
Rscript scripts/observation_to_grid.R --observations "${STGNN_OBSERVATIONS}" --template "${STGNN_TEMPLATE_PATH}" --nodes "${nodes_parquet}" --output-json "${diagnostic_json}" --output-parquet "${diagnostic_parquet}"

Rscript -e "testthat::test_dir('tests/testthat')"
source hpc/env_python.sh
python python/contract_smoke.py --nodes "${nodes_parquet}" --edges "${edges_parquet}" --output "${contract_json}"

Rscript scripts/assemble_preflight_manifest.R --output "${manifest_json}" --environment "${environment_json}" --observation "${observation_json}" --inventory "${inventory_json}" --diagnostic "${diagnostic_json}" --diagnostic-counts "${diagnostic_parquet}" --graph-qa "${graph_qa_json}" --canonical "${canonical_json}" --contract "${contract_json}" --template "${STGNN_TEMPLATE_PATH}" --nodes "${nodes_parquet}" --edges "${edges_parquet}" --job-ids "${STGNN_JOB_IDS:-}"
