#!/usr/bin/env bash
set -euo pipefail

# Set STGNN_PYTHON_ENV only after the Atlas GPU environment has been tested.
if [[ -z "${STGNN_PYTHON_ENV:-}" ]]; then
  echo "STGNN_PYTHON_ENV is not set; refusing to guess a Python environment." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! -f "${STGNN_PYTHON_ENV}/bin/activate" ]]; then
  echo "Python activation script not found: ${STGNN_PYTHON_ENV}/bin/activate" >&2
  return 2 2>/dev/null || exit 2
fi

source "${STGNN_PYTHON_ENV}/bin/activate"
python --version
