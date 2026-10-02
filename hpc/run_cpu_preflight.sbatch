#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=16
#SBATCH --time=00:30:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/%x-%j.err

set -euo pipefail
source hpc/env_r.sh

mkdir -p "${STGNN_OUTPUT_ROOT}/logs/slurm" "${STGNN_OUTPUT_ROOT}/preflight"
Rscript scripts/atlas_r_environment_report.R \
  --output "${STGNN_OUTPUT_ROOT}/preflight/r_environment.json"
