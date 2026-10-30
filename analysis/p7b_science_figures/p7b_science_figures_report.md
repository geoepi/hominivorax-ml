# P7B Science-First Figure Generation and Focal-Region Extraction

## Scope and writing boundary

P7B generated a compact science-review figure set, technical captions, core
tables, and source/provenance records from canonical P0--P7 artifacts. No
model fitting, retraining, tuning, recalibration, feature selection, SHAP,
permutation importance, partial dependence, ALE, or leave-one-predictor-out
refitting was performed. No manuscript Results, Discussion, Methods,
Introduction, abstract, or submission narrative was generated.

## Canonical contract

| Item | Locked value |
|---|---|
| Scientific model | `STRUCTURED_A3` |
| Frozen artifact SHA-256 | `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e` |
| Operational proxy | `E0_LAST_AVAILABLE` |
| Horizons | h=1, h=2, h=3 |
| Focal CRS | EPSG:4326 |
| Focal bbox | longitude -107.5 to -96.0; latitude 24.0 to 33.0 |
| Focal cells | 1,689 |
| Focal h=1 interval | 2026-W17 through 2026-W37 |
| Map weeks | 2026-W17, W22, W27, W32, W37 |

## Atlas focal extraction

The canonical P2 archive was read through the authorized WSL/Ubuntu Atlas route
using the repository `hpc/env_python.sh` bootstrap. The extraction script was
`analysis/p7b_science_figures/scripts/extract_focal_region_atlas.py`.

- Source archive: `/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/predictions/rolling_origin_predictions.parquet`
- Source SHA-256: `918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170`
- Bounded focal rows: 35,469 cell-weeks
- Focal cells: 1,689
- Map rows: 8,445 = 1,689 cells × 5 map weeks
- h=1 target interval: 2026-W17--2026-W37
- Derived Atlas parquet: `/project/disease_ecology/STGNN-output/p7b_science_figures_20261029/focal_extract/mexico_texas_focal_h1_2026w17_w37.parquet`
- The full P2 archive was not copied into the repository.
- Support classes were not approximated: canonical P6 support coverage is not
  complete across the full focal interval, so no focal support time series was
  generated.

The exact extraction record is
`analysis/p7b_science_figures/results/focal_extraction_manifest.json`.

## Main figures

### Figure 1 — Domain, focal region, and model framework

Output:
`analysis/p7b_science_figures/figures/main/figure_01_domain_framework.svg`

Panels show the canonical domain and fixed bbox, the focal cell grid, the
frozen hurdle structure, and the E0 issue-time environmental-state rule.
The domain plot uses retained cell centers and domain-region labels. State
boundaries were not added because state intersections were not retained in the
canonical P2 archive.

### Figure 2 — Predictive performance across horizons

Output:
`analysis/p7b_science_figures/figures/main/figure_02_predictive_performance.svg`

Panels use canonical P2 all-domain metrics for Brier score, AUPRC, calibration
intercept/slope, and AUROC for h=1--3. Values are read directly from
`analysis/p2_operational_nowcast/results/horizon_metrics.csv`.

### Figure 3 — Mexico-Texas spatial-temporal dynamics

Primary occurrence candidate:
`analysis/p7b_science_figures/figures/main/figure_03_mexico_texas_occurrence.svg`

Expected-count candidate:
`analysis/p7b_science_figures/figures/main/figure_03_mexico_texas_expected_count_candidate.svg`

The occurrence candidate uses fixed probability scales across the five map
weeks and overlays observed positive cells. Its time series compares observed
positive cells with the expected number of positive cells, defined as
`sum_i p_occurrence`. The expected-count candidate uses the same spatial,
temporal, and h=1 filters and shows `sum_i expected_count` as a separate
technical candidate.

The compact plotted data are:

- `analysis/p7b_science_figures/results/plot_data/figure_03_focal_h1_map_data.csv`
- `analysis/p7b_science_figures/results/plot_data/figure_03_focal_h1_time_series.csv`

### Figure 4 — Issue-time environmental proxy validation

Output:
`analysis/p7b_science_figures/figures/main/figure_04_issue_time_proxy_validation.svg`

The four panels show E0 minus REALIZED_ENV differences for Brier, AUPRC,
conditional positive-count MAE, and full expected-count MAE. Intervals are
the canonical P5A target-week bootstrap intervals from
`analysis/p5a_environmental_proxy/results/bootstrap_intervals.csv`.

### Figure 5 — Predictor associations

Output:
`analysis/p7b_science_figures/figures/main/figure_05_predictor_associations.svg`

The occurrence and conditional positive-count panels show signed fitted
coefficient associations with explicit scaling-category markers. The stability
panel is limited to the four predictors with canonical rolling-origin
summaries. There is no global coefficient-magnitude ranking and no causal or
feature-importance interpretation.

### Figure 6 — Support and extrapolation

Output:
`analysis/p7b_science_figures/figures/main/figure_06_support_extrapolation.svg`

Panels show E0 support proportions, the reused canonical P4 support display,
and P4 performance by support class. P4 thresholds and class definitions are
unchanged.

## Supplementary candidates

- S1 reliability curves:
  `analysis/p7b_science_figures/figures/supplement/S1_reliability_curves.svg`
- S2 frontier-definition sensitivity:
  `analysis/p7b_science_figures/figures/supplement/S2_frontier_sensitivity.svg`
- S3 canonical P3 count diagnostic reuse:
  `analysis/p7b_science_figures/figures/supplement/S3_count_diagnostics_reference.png`
- S4 environmental proxy error and support transitions:
  `analysis/p7b_science_figures/figures/supplement/S4_proxy_error_support_transitions.svg`

## Core tables

The following are exact copies of the canonical P7 tables, with no scientific
value changes:

- `analysis/p7b_science_figures/tables/table_1_model_data.csv`
- `analysis/p7b_science_figures/tables/table_2_occurrence.csv`
- `analysis/p7b_science_figures/tables/table_3_count.csv`
- `analysis/p7b_science_figures/tables/table_4_proxy.csv`

## Captions and provenance

Technical captions are in `analysis/p7b_science_figures/captions/`. The source
registry is:

`analysis/p7b_science_figures/results/figure_source_registry.csv`

It records source phase, source file, fields, transformations, filters,
geographic/temporal subsets, plotting script, output hashes, and plotted-data
hashes. Compact extraction and plotted-data records are under
`analysis/p7b_science_figures/results/`.

## Validation

Focused validation:

```text
P7B_OUTPUT_VALIDATION_PASS
```

The validation checks the frozen model hash, fixed focal bbox, 1,689-cell
contract, exact map-week set, exact h=1 interval, aggregation definitions,
source-registry completeness, coefficient scale labels, output existence, and
no-model-fitting metadata. Underlying plotted-data files were regenerated
twice and compared by SHA-256; the underlying scientific values were
identical. SVG/PDF-style rendering metadata is treated separately from the
plotted-data hashes.

## Source limitations retained for scientific review

1. The canonical P2/P6 joins do not provide complete focal support classes for
   every W17--W37 cell-week, so a focal support time series is omitted.
2. State-level boundaries are not retained in the P2 archive; the domain and
   focal maps use canonical cell centers and domain-region labels.
3. Coefficient scaling is mixed; Figure 5 is a signed-association display, not
   a global importance ranking.
4. Coefficient stability is available for four augmented predictors only.
5. The expected-count map and count-time-series version of Figure 3 remains a
   technical candidate for scientific review alongside the occurrence version.

## P7B decision

P7B_SCIENCE_FIGURES_SUPPORTED_WITH_LIMITATIONS
