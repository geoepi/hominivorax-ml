#!/usr/bin/env bash
set -euo pipefail

# Canonical starting stack from Task 1. Validate on a compute node before
# treating this wrapper as production-ready.
module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 \
  intel-oneapi-mkl/2023.2.0 r/4.4.3

export STGNN_OUTPUT_ROOT="${STGNN_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output}"
export STGNN_REPOSITORY_ROOT="${STGNN_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"

echo "STGNN_OUTPUT_ROOT=${STGNN_OUTPUT_ROOT}"
echo "STGNN_REPOSITORY_ROOT=${STGNN_REPOSITORY_ROOT}"
R --version | head -n 1
