# Task 2E — Revised production dataset

Status: verified on Atlas in refresh job `20844162` and baseline-contract
validation job `20844173`. The authoritative artifacts are outside Git at
`/project/disease_ecology/STGNN-output/revised_model_data/`. The Task 2D audit
output under `STGNN-output/revised_domain/` remains unchanged.

## Observation source

The production refresh uses:

```text
/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv
```

| Quantity | Refreshed value |
|---|---:|
| SHA-256 | `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e` |
| rows | 136,714 |
| valid coordinates / dates | 136,714 / 136,714 |
| date range | 2022-02-10 through 2026-07-31 |
| Task 2D source SHA-256 | `099f5fcc61dbd3686bd9bfd0dbfb0a4e37a36f2cba8b443580d2c456544f8a41` |
| Task 2D row count | 136,670 |
| row-count delta | +44 |

The prior source was not available for an exact row-level diff on Atlas, so the
manifest records the source change as a verified hash and row-count refresh,
not as a claim that every added row was independently matched to an old row.
The 44-row delta is entirely U.S. detections: 43 in Texas and one in New
Mexico. All 44 are inside the revised domain and environmental-support
intersection. They occur from 2026-06-03 through 2026-07-31; the source
classification and U.S. assignment tables provide the row-level audit.

## Fixed domain and graph

The domain remains the fixed Task 2D rule: Mexico plus the existing canonical
U.S. footprint at latitude strictly below 40°N, intersected with the frozen
environmental-support mask. No observation locations, buffers, convex hulls,
occupancy, or invasion-front tracing define the domain.

| Artifact | Value |
|---|---:|
| revised model nodes | 10,037 |
| directed queen edges | 77,614 |
| undirected edges | 38,807 |
| connected components | 4 |
| isolated nodes | 3 |
| mean degree | 7.7328 |
| edge checksum | `539876a1528c84f2bf7ab97f5b8f20b3da480cb1c705ac47611542e4a00ad9a7` |

The canonical node order and induced edge set are checked against the Task 2D
artifacts before the refreshed arrays are written.

## Response contract

The selected response period is 2025-W01 through 2026-W29: 81 weeks. Counts
are recorded detections assigned to a revised-domain node-week; presence is
exactly `count > 0`. A zero therefore means no recorded detection, not
confirmed biological absence.

| Quantity | Value |
|---|---:|
| target node-weeks | 812,997 |
| positive node-weeks | 14,848 |
| positive fraction | 0.0182633 |
| occupied nodes | 1,504 |
| weekly mean / median detections | 532.0123 / 583 |
| weekly coefficient of variation | 0.5370 |
| Mexico positive node-weeks | 14,818 |
| U.S.-to-40°N positive node-weeks | 30 |

The candidate-start comparison remains descriptive and selects 2025-W01. The
candidate positive fractions for W01, W05, W09, and W13 are 1.8263%, 1.9197%,
2.0203%, and 2.1164%, respectively. Later starts do not improve the
information available for the planned validation design.

## Arrays and predictors

| Artifact | Shape |
|---|---:|
| `raw/dynamic_features.npy` | `[81, 10037, 12]` |
| `raw/dynamic_history_features.npy` | `[185, 10037, 12]` |
| `raw/static_features.npy` | `[10037, 10]` |
| `raw/targets_count.npy` | `[81, 10037]` |
| `raw/targets_presence.npy` | `[81, 10037]` |

The 24 current-week predictors are the 12 environmental variables, five
`log1p` livestock-density variables, five livestock imputation indicators, and
`week_sin`/`week_cos` in that order. Coordinates, node IDs, response lags,
rolling features, and spatial-neighborhood predictors are excluded. The
environmental history is retained for future antecedent-feature work but is
not used by the Task 2E baseline.

## Splits and safeguards

Development weeks are 2025-W01 through 2026-W16 (68 weeks). The terminal
holdout is 2026-W17 through 2026-W29 (13 weeks), and is represented in the
split manifests but is never used for fitting, tuning, or predictive scoring.

| Fold | Training period | Validation period |
|---:|---|---|
| 1 | 2025-W01–W26 | 2025-W27–W39 |
| 2 | 2025-W01–W39 | 2025-W40–W52 |
| 3 | 2025-W01–W52 | 2026-W01–W08 |
| 4 | 2025-W01–2026-W08 | 2026-W09–W16 |

The machine-readable contract is in
`manifests/revised_production_manifest.json`, with source classification,
weekly regime, candidate screening, regional, seasonal, latitude, and graph
diagnostics under `diagnostics/`.
