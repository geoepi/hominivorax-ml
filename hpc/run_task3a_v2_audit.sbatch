#!/usr/bin/env bash
#SBATCH --job-name=stgnn-task3a-audit
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/task3a_audit_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/task3a_audit_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh

python scripts/run_task3a_v2_audit.py \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --source /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv \
  --output /project/disease_ecology/STGNN-output/v2_audit
