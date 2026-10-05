# STGNN Soil Feature Screening — Authoritative Phase S2 fixed-theta reproducibility gate

Status: **AUTHORITATIVE PHASE S2 COMPLETE**

## Interpretation and baseline gate

- Historical theta provenance: **PASSED**.
- Historical NLL reconstruction: **PASSED**.
- Old rescore-vs-refit equality criterion: **INVALID AS A REPRODUCIBILITY REQUIREMENT**.
- Fixed-theta refit A versus independent fixed-theta refit B: **PASSED**.
- Authoritative protocol: 30 predictors, penalty 0.01, theta fixed at 0.7018903965556372, exact joint hurdle NLL, F1--F4 only.

Only the fixed-theta refit is used for soil comparisons; historical fold-specific theta fits and fixed-theta rescoring are provenance/diagnostic objects.

## Soil task execution

- Individual soil tasks: 32; canonical nodes: 10037; terminal response loaded: no.
- Soil scaling was fold-safe and persisted in `soil_scaling_parameters.csv`.
- Individual classifications were frozen before any combination task was considered.

## Frozen individual guardrails

NLL worst-fold degradation tolerance: 0.005; primary metric worst-fold tolerance: 0.005; calibration distance worst-fold tolerance: 0.1; stable coefficient sign minimum: 3/4 folds.

| Feature | Dimension | Classification | Mean joint-NLL improvement | Mean Brier-skill improvement | Mean PR-AUC improvement | Main limitation |
|---|---|---:|---:|---:|---:|---|
| cec_0_15 | chemistry | HOLD | -2.20594e-05 | 0.000241527 | -0.000493862 | none identified by frozen guardrails |
| bdod_0_15 | bulk_density | ADVANCE | 7.79334e-07 | 0.000171938 | 0.00296927 | none identified by frozen guardrails |
| ocd_0_15 | organic_matter | HOLD | -0.000233795 | 0.000105772 | 0.00141374 | none identified by frozen guardrails |
| clay_0_15 | texture | ADVANCE | 0.000241322 | 0.00149922 | 0.00665781 | none identified by frozen guardrails |
| water_difference_wv0033_minus_wv0010_0_15 | water_retention | ADVANCE | 0.000169767 | 0.00124665 | 0.00477415 | none identified by frozen guardrails |
| nitrogen_100_200 | nitrogen | ADVANCE | 3.51974e-05 | 0.000457657 | 0.00309539 | 5000-m nitrogen source |
| phh2o_0_15 | chemistry | ADVANCE | 0.000110473 | 0.000246342 | -0.00174546 | none identified by frozen guardrails |
| bdod_100_200 | bulk_density | HOLD | 3.57752e-05 | 0.000331755 | 0.00452964 | none identified by frozen guardrails |

## Redundancy resolution

See `redundancy_resolution.csv`. Retention is limited to one representative per soil dimension unless a later controlled combination screen provides independent evidence.

## Combination screen

Only preselected pairs of distinct retained dimensions were evaluated; no all-pairs, three-way, or interaction search was performed.

| Pair | Mean joint-NLL improvement | Classification |
|---|---:|---:|
| clay_0_15+bdod_0_15 | 0.000246335 | ADVANCE |
| clay_0_15+nitrogen_100_200 | 0.000201283 | ADVANCE |
| clay_0_15+phh2o_0_15 | 0.000265173 | ADVANCE |
| clay_0_15+water_difference_wv0033_minus_wv0010_0_15 | 0.000301791 | ADVANCE |

## Final controlled augmentation specification

| Rank | Feature | Dimension | Depth | Source resolution | Rationale |
|---:|---|---|---|---|---|
| 1 | clay_0_15 | texture | 0-15 cm | 1000 m | advanced under frozen fixed-theta guardrails with stable fold behavior and distinct soil dimension |
| 2 | water_difference_wv0033_minus_wv0010_0_15 | water_retention | 0-15 cm | 1000 m | advanced under frozen fixed-theta guardrails with stable fold behavior and distinct soil dimension |

## Boundary checks

- No Phase S1 aggregation rerun.
- No response data, F5/F6, terminal/later outcomes, roads, night illumination, STGNN fitting, V2-A modification, theta re-estimation, or supervised feature selection.

SOIL SPECIFICATION FROZEN FOR CONTROLLED AUGMENTATION
