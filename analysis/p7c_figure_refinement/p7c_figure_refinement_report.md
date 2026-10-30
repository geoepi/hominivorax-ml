# P7C Figure Refinement and Cartographic Revision

## Scope and boundary

P7C refines the P7B science-facing figure set using canonical P0-P7 artifacts and a bounded cartographic source. It does not fit, retrain, tune, recalibrate, select, or modify a model; change the E0 proxy; change support thresholds; change the focal region; or change map weeks and horizons. The work is limited to rendering, source-traceable descriptive aggregation, cartographic orientation, captions, and provenance.

## Canonical starting state

- P7B merge: `af6bce100799b5b32b3cb028c26afc7e698aaee7`.
- Scientific model: `STRUCTURED_A3`.
- Frozen artifact SHA-256: `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.
- Operational proxy: `E0_LAST_AVAILABLE`.
- Production configuration: `config/p6_production_config.json`.
- Fixed focal region: EPSG:4326, longitude `-107.5` to `-96.0`, latitude `24.0` to `33.0`, 1,689 canonical cells.
- Fixed map weeks: `2026-W17`, `2026-W22`, `2026-W27`, `2026-W32`, `2026-W37`.
- Fixed time interval: `2026-W17` through `2026-W37`, h=1.

The repository freeze verifier was executed in the authorized Atlas environment and returned `PRODUCTION_MODEL_FREEZE_VERIFIED`. The local focused P7C validator also confirmed the frozen hash and required P5A/P6 source artifacts.

## Cartographic source audit

The boundary source was read from Atlas using the authorized WSL/Ubuntu `atlas-ssh` route:

`/project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg`, layer `study_states`.

The source contains 492 features. Its user-input CRS is reported as unknown, but its WKT identifies WGS84 geographic coordinates with an Albers Equal Area conversion and kilometre units. P7C applies `sf::st_make_valid()` followed by transformation to EPSG:4326. The local cartographic copy is recorded at `results/boundaries/study_states.gpkg` with SHA-256 `b2176d82a2d0b4ec44d1c23c5bac5ba43fbe5a53eeede593c4ea0f5cf8924f58`. Boundaries are used for orientation only; they do not alter scientific records or subsets.

## Figure set

### Figure 1 — Domain, focal region, and model framework

Outputs:

- `figures/main/figure_01_domain_framework.svg`
- `figures/main/figure_01_domain_framework.png`
- `captions/figure_01.caption.md`

Panels show the canonical domain and grid, the fixed Mexico-Texas crop, the frozen STRUCTURED_A3 hurdle structure, and the E0 issue-time input timeline. The maps use cell surfaces rendered with `ggplot2::geom_tile`, common geographic orientation, boundaries, a north arrow, and a scale bar.

### Figure 2 — Predictive performance across horizons

Outputs:

- `figures/main/figure_02_predictive_performance.svg`
- `figures/main/figure_02_predictive_performance.png`
- `captions/figure_02.caption.md`

The figure uses canonical P2 metrics for Brier score, AUPRC, calibration intercept, calibration slope, and AUROC. Horizon colors and ordering are shared across panels. No metrics are re-estimated.

### Figure 3 — Mexico-Texas spatial-temporal dynamics

Outputs:

- `figures/main/figure_03_mexico_texas_occurrence.svg`
- `figures/main/figure_03_mexico_texas_occurrence.png`
- `figures/main/figure_03_mexico_texas_expected_count_candidate.svg`
- `figures/main/figure_03_mexico_texas_expected_count_candidate.png`
- `captions/figure_03_occurrence.caption.md`
- `captions/figure_03_count.caption.md`

The occurrence candidate contains five h=1 maps at the fixed target weeks, observed-positive overlays, expected positive-cell burden, and the corresponding observed-positive-cell time series. The expected-count candidate retains the same extent, weeks, and geometry while displaying full hurdle expected count and the candidate count time series. Both candidates are preserved for scientific review; the expected-count version is not treated as an automatic replacement.

The bounded focal extraction contains 8,445 rows: 1,689 cells across five target weeks. The exact filter and fields are recorded in `results/focal_extract_manifest.json` and the compact extract in `results/mexico_texas_focal_h1_2026w17_w37.csv`.

### Figure 4 — Issue-time environmental proxy validation

Outputs:

- `figures/main/figure_04_issue_time_proxy_validation.svg`
- `figures/main/figure_04_issue_time_proxy_validation.png`
- `captions/figure_04.caption.md`

The figure displays canonical P5A paired E0-minus-REALIZED_ENV differences for Brier, AUPRC, conditional positive-count MAE, and full expected-count MAE with the available dependence-aware intervals. The zero reference is explicit. REALIZED_ENV is the retrospective realized-environment reference; E0 is the latest legitimately available environmental state held across h=1 to h=3. The figure does not imply that future environmental conditions are constant.

### Figure 5 — Signed predictor associations

Outputs:

- `figures/main/figure_05_predictor_associations.svg`
- `figures/main/figure_05_predictor_associations.png`
- `captions/figure_05.caption.md`

Occurrence- and count-component coefficient displays are grouped by predictor family and marked by scale class. The bounded stability subset shows only the four predictors with canonical rolling-origin stability summaries. The display is intentionally not a global feature-importance ranking. Coefficients represent conditional predictive associations; comparisons are most defensible within comparable scaling classes, and correlated predictors can redistribute coefficient magnitude. No causal interpretation is assigned.

### Figure 6 — Support and extrapolation

Outputs:

- `figures/main/figure_06_support_extrapolation.svg`
- `figures/main/figure_06_support_extrapolation.png`
- `figures/main/figure_06_support_canonical_p4.png`
- `captions/figure_06.caption.md`

The E0-filtered support proportions, canonical P4 support display, occurrence Brier by support class, and a wrapped support-definition panel are shown. Support classes mean predictor-space representation relative to the reference distribution: SUPPORTED indicates conditions well represented in training data, CAUTION indicates less well-supported conditions, and EXTRAPOLATIVE indicates conditions substantially outside training support. These categories are not confidence intervals, not direct measures of correctness, and not causal categories. The complete cell-level P4 map is reused because the retained canonical records do not provide a complete new cell-level support surface for re-rendering.

## Supplementary candidates

- `S1_reliability_curves`: canonical P2 reliability curves.
- `S2_frontier_sensitivity`: canonical P3 frontier-definition sensitivity.
- `S3_count_diagnostics_reference`: canonical P2/P3 count diagnostic raster reused without new analysis.
- `S4_proxy_error_support_transitions`: canonical P5A environmental error and support-transition summaries.

Each has a technical caption and source entry. The set remains bounded at four supplementary figures.

## Tables

The core P7B tables are copied without numerical modification to `tables/`:

- `table_1_model_data.csv`
- `table_2_occurrence.csv`
- `table_3_count.csv`
- `table_4_proxy.csv`

## Source and provenance records

The panel-level registry is `results/figure_source_registry.csv`. It records source phase, source file and fields, filters, transformations, geographic and temporal subsets, plotting script, output file, and output hash. `results/rendering_contract.json` records the fixed crop, weeks, h=1 filter, `geom_tile` surface contract, boundary layer, north-arrow and scale-bar methods, and no-point-surface rule. `results/boundary_audit.json`, `results/focal_extract_manifest.json`, `results/figure_output_hashes.csv`, and `results/run_metadata.json` provide cartographic, extraction, output, and runtime provenance.

## Validation and reproducibility

Focused validation returned `P7C_OUTPUT_VALIDATION_PASS`. It checked the frozen artifact hash, canonical source presence, exact focal geometry and weeks, cell and row counts, h=1 filtering, aggregation definitions, boundary provenance, registry completeness, required outputs, caption caveats, no-model-fitting metadata, and plotted-data hashes.

The generator was run twice from the same checkout. All underlying plotted-data CSV hashes were identical, including the focal map/time-series data, performance data, proxy differences, coefficient displays, support proportions, reliability data, frontier sensitivity, environmental-error data, and support transitions. SVG/PNG rendering was regenerated from those identical plotted-data sources. R emitted only known locale-startup warnings and ggspatial notices about geographic scale variation in scale bars; these do not alter the plotted data or validation result.

## Limitations carried forward

1. The focal-region support map is a canonical P4 display rather than a newly re-rendered cell-level surface.
2. The supplied boundary layer has an unknown declared CRS and is transformed from its WKT-described WGS84-based Albers representation for cartographic orientation.
3. Figure 5 is a mixed-scaling signed-association display, not a globally comparable importance ranking.
4. The expected-count Figure 3 remains a candidate alternative pending scientific review against the occurrence representation.
5. The P7B source archives and support records constrain the available spatial and temporal display fields; no missing support classes are approximated.

## P7C decision

P7C_FIGURE_REFINEMENT_SUPPORTED_WITH_LIMITATIONS
