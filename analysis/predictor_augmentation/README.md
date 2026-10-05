# Controlled predictor augmentation

This workstream evaluates four development-only specifications against the
frozen V2-A hurdle protocol:

| Model | Added predictors |
|---|---|
| A0 | none; frozen V2-A reference |
| A1 | `road_density`, `night_illumination` |
| A2 | `clay_0_15`, `water_difference_wv0033_minus_wv0010_0_15` |
| A3 | all four additions |

The workstream does not modify production V2-A, the response, the graph, the
STGNN architecture, or the terminal evaluation. It uses only F1--F4, the
10,037-node canonical grid, penalty `0.01`, and fixed theta
`0.7018903965556372` under the exact joint hurdle objective.

## Execution

Run on Atlas from the repository checkout after the frozen V2-A front features
and revised production data have been created:

```bash
Rscript analysis/predictor_augmentation/scripts/aggregate_road_night_features.R \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --canonical-mask /project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation/static \
  --road-raster /project/disease_ecology/NWScrewworm/data/raw_data/road_density/road_density_crp.tif \
  --night-raster /project/disease_ecology/NWScrewworm/data/raw_data/night_illumination/night_illum_crp.tif

python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py prepare \
  --model-output /project/disease_ecology/STGNN-output/revised_model_data \
  --front-features /project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet \
  --anthropogenic-features /project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet \
  --soil-features /project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation

python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py worker \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --task-id "$SLURM_ARRAY_TASK_ID"

python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py baseline \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --reference-metrics analysis/predictor_augmentation/provenance/fixed_theta_baseline_reference.csv

python analysis/predictor_augmentation/scripts/run_predictor_augmentation.py finalize \
  --output-root /project/disease_ecology/STGNN-output/predictor_augmentation \
  --reference-manifest analysis/predictor_augmentation/provenance/fixed_theta_baseline_manifest.json
```

The worker is restartable and writes each task result and prediction file by
temporary-file-plus-rename. A1--A3 workers refuse to run until the A0 baseline
gate passes. Runtime artifacts belong under the external STGNN output root;
the repository stores the code and the frozen provenance inputs only.

