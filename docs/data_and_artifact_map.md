# Canonical data and artifact map

Protected source data and large generated products remain outside Git. The paths below are Atlas-side locations used by the frozen workflow; access requires the project account and the configured Atlas environment.

| Artifact | Canonical Atlas location | Repository reference | Notes |
|---|---|---|---|
| Revised domain, response tensors, nodes, weeks | `/project/disease_ecology/STGNN-output/revised_model_data` | `docs/current_model_specification.md` | Contains the 10,037-node production bundle and 2025-W01–2026-W29 response horizon. |
| Causal history/front features | `/project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet` | `docs/modeling_decisions/002_v2a_feature_selection.md` | One row per week/node; history cutoff must precede forecast week. |
| Livestock/environmental static and dynamic arrays | `/project/disease_ecology/STGNN-output/revised_model_data/raw` | `docs/predictor_dictionary.csv` | Dynamic tensors, calendar features, static livestock features, nodes, and targets. |
| Road/night static features | `/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet` | `analysis/structured_a3_final_comparison/results/a3_feature_manifest.json` | Checksummed anthropogenic source for the two A3 additions. |
| Soil node features | `/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet` | `docs/modeling_decisions/003_soil_feature_screening.md` | Checksummed protected soil artifact; not committed to Git. |
| Authoritative observation source | `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv` | `analysis/structured_a3_evaluation/results/data_refresh_provenance.json` | External observation source; no refresh or deduplication mutation performed by evaluation. |
| F1–F4 structured comparison | `/project/disease_ecology/STGNN-output/structured_a3_final_comparison` | `analysis/structured_a3_final_comparison/` | Development-only A0/A3 fits, manifests, metrics, and report. |
| Historical exposed holdout evaluation | `/project/disease_ecology/STGNN-output/worktrees/structured-a3-evaluation/analysis/structured_a3_evaluation/results` | `analysis/structured_a3_evaluation/` | Compact summaries and frozen evaluation provenance are committed; source data are not. |

## Provenance rules

- Joins use the canonical `model_node_id` sequence 0–10,036.
- Static artifact checksums are recorded in the A3 feature manifest and evaluation run summary.
- The immutable evaluation manifest was frozen before outcomes and has SHA-256 `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61`.
- Do not add raw rasters, Parquet tables, model checkpoints, observation files, credentials, caches, or Atlas job outputs to this repository.
