#!/usr/bin/env bash
set -euo pipefail

# Canonical starting stack from Task 1. Validate on a compute node before
# treating this wrapper as production-ready.
module purge
module load udunits proj geos/3.12.1 gdal/3.8.5 \
  intel-oneapi-mkl/2023.2.0 r/4.4.3

# Atlas R packages installed outside Git for the validated project runtime.
export STGNN_R_LIBS_USER="${STGNN_R_LIBS_USER:-/project/disease_ecology/STGNN-r-lib}"
export R_LIBS_USER="${STGNN_R_LIBS_USER}:/home/john.humphreys/R/x86_64-pc-linux-gnu-library/4.4"

export STGNN_OUTPUT_ROOT="${STGNN_OUTPUT_ROOT:-/project/disease_ecology/STGNN-output}"
export STGNN_REPOSITORY_ROOT="${STGNN_REPOSITORY_ROOT:-/project/disease_ecology/STGNN}"

echo "STGNN_OUTPUT_ROOT=${STGNN_OUTPUT_ROOT}"
echo "STGNN_REPOSITORY_ROOT=${STGNN_REPOSITORY_ROOT}"
R --version | head -n 1
