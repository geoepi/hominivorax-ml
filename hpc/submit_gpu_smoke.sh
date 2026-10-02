#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "Usage: $0 <validated-gpu-partition>" >&2
  exit 2
fi

gpu_partition="$1"
sbatch \
  --account=disease_ecology \
  --partition="${gpu_partition}" \
  --nodes=1 \
  --ntasks=1 \
  --gres=gpu:1 \
  --time=00:20:00 \
  --output=/project/disease_ecology/STGNN-output/logs/slurm/gconvgru-%j.out \
  --error=/project/disease_ecology/STGNN-output/logs/slurm/gconvgru-%j.err \
  hpc/run_gpu_smoke.sbatch
