# Canonical data and artifact map

Protected source data and large generated products remain outside Git. Paths
are separated by vintage and workflow. Templates in Git are not evidence of
the currently deployed configuration; access to Atlas locations requires the
project account and configured environment.

| Artifact | Canonical Atlas location | Repository reference | Notes |
|---|---|---|---|
| Original frozen model and provenance | Tracked in the repository; no protected source table is included | `config/production_model_freeze.json`; `analysis/structured_a3_evaluation/results/final_a3_model.json` | W16 fit, 34 predictors, 10,037 nodes; original freeze is immutable. |
| Previously active W29 full-fit model | `/project/disease_ecology/STGNN-output/structured_a3_fullfit` | Current isolation record summarized in `docs/current/status.md` | W29 full-fit model SHA begins `1cb694f`; its active configuration hash begins `f51038`. This is an Atlas deployment record, not the `config/atlas-production.example.yaml` template. |
| W44 candidate observation source | `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-11-13.csv` | `analysis/structured_a3_data_refresh_2026w44/candidate_data_vintage_manifest.json` | SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`; 164,767 records through W46; W45–W46 excluded from the W44 fit. Completeness and revision caveats remain. |
| W44 candidate fit and full-fit products | `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44` | `analysis/structured_a3_data_refresh_2026w44/` | Candidate SHA-256 `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b`; descriptive fitted-period products; not production-qualified. |
| W44 Q1 row-level prediction archive | `/project/disease_ecology/STGNN-output/structured_a3_2026w44_q1_retrospective_attempt02` | Aggregate only: `analysis/structured_a3_data_refresh_2026w44/qualification_execution/results/2026w44_q1_retrospective/` | The 2,348,658-row prediction archive remains on Atlas. Aggregate scoring is descriptive because target maturity is uncertified; scientific decision is `NOT_ASSIGNED`. |
| W44 development input audit | Atlas source and predictor bundle; see manifests | `analysis/structured_a3_data_refresh_2026w44/` | Provisional endpoint W44, accepted corrected source, and provenance/limitations are recorded without changing the original W16 freeze. |
| Causal history/front features | `/project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet` | `docs/history/modeling_decisions/002_v2a_feature_selection.md` | One row per response week/node; production builders enforce issue-time cutoffs. |
| Static/dynamic predictors | `/project/disease_ecology/STGNN-output/revised_model_data/raw`; road/night and soil paths in the configured manifest | `docs/current/predictors.csv`; `analysis/structured_a3_final_comparison/results/a3_feature_manifest.json` | Protected inputs remain on Atlas and are joined by canonical node order. |
| F1–F4 structured comparison | `/project/disease_ecology/STGNN-output/structured_a3_final_comparison` | `analysis/structured_a3_final_comparison/` | Historical development-only A0/A3 fits and decision record. |
| Historical exposed holdout evaluation | Atlas evaluation archive recorded in its manifest | `analysis/structured_a3_evaluation/` | W17–W29 outcomes were historically exposed; they are not prospective evidence. |

## Provenance rules

- Joins use the canonical `model_node_id` sequence 0–10,036.
- Static artifact checksums are recorded in the A3 feature manifest and evaluation run summary.
- The immutable evaluation manifest was frozen before outcomes and has SHA-256 `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61`.
- Do not add raw rasters, Parquet tables, model checkpoints, observation files, credentials, caches, or Atlas job outputs to this repository.
- `config/atlas-production.example.yaml` is a deployment template. It does not establish the current deployed tag, active paths, or the current production source vintage.
