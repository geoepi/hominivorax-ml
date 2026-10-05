#!/usr/bin/env bash
#SBATCH --job-name=stgnn-predictor-augmentation-prepare
#SBATCH --account=disease_ecology
#SBATCH --partition=development
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_prepare_%j.out
#SBATCH --error=/project/disease_ecology/STGNN-output/logs/predictor_augmentation_prepare_%j.err

set -euo pipefail
cd /project/disease_ecology/STGNN
export STGNN_PYTHON_ENV=/project/disease_ecology/STGNN-python-venv
source hpc/env_python.sh
source hpc/env_r.sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ROOT=/project/disease_ecology/STGNN-output/predictor_augmentation

Rscript analysis/predictor_augmentation/scripts/aggregate_road_night_features.R \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --canonical-mask /project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif \
  --output-root "$ROOT/static" \
  --road-raster /project/disease_ecology/NWScrewworm/data/raw_data/road_density/road_density_crp.tif \
  --night-raster /project/disease_ecology/NWScrewworm/data/raw_data/night_illumination/night_illum_crp.tif

python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py prepare \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features "$ROOT/static/road_night_node_features.parquet" \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv \
  --output-root "$ROOT"

