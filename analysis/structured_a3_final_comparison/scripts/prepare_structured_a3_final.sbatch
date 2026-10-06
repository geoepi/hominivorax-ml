#!/usr/bin/env bash
#SBATCH --job-name=stgnn-structured-a3-prepare
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/structured_a3_prepare_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/structured_a3_prepare_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN-output/worktrees/structured-a3-final-comparison
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source /project/disease_ecology/STGNN/hpc/env_python.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python analysis/structured_a3_final_comparison/scripts/run_structured_a3_final.py prepare \
  --output-root /project/disease_ecology/STGNN-output/structured_a3_final_comparison \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv
