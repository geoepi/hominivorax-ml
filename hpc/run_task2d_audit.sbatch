#!/usr/bin/env bash
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/slurm/task2d-audit-%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/slurm/task2d-audit-%j.err
set -euo pipefail

cd /project/disease_ecology/STGNN
source hpc/env_r.sh
mkdir -p /project/disease_ecology/STGNN-output/{revised_domain,manifests,logs/slurm}

: "${STGNN_BOUNDARY_PATH:?set STGNN_BOUNDARY_PATH to the existing Atlas boundary artifact}"
git_sha="$(git rev-parse HEAD)"
STGNN_GIT_BRANCH="$(git branch --show-current)" \
Rscript scripts/run_revised_domain_audit.R \
  --output-root /project/disease_ecology/STGNN-output \
  --observation-path /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv \
  --boundary-path "${STGNN_BOUNDARY_PATH}" \
  --git-sha "${git_sha}"
