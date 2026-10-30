# P7D Cartographic Corrections and Operational Forecast Visualization

## Scope and governance

P7D is a bounded cartographic and descriptive visualization phase. The frozen
`STRUCTURED_A3` model, `E0_LAST_AVAILABLE` proxy, P4 support thresholds, and
canonical P0–P6 outputs were not modified. No model fitting, refitting,
recalibration, feature-importance method, or new uncertainty analysis was run.

Atlas access used the authorized WSL/Ubuntu `atlas-ssh` route. The Atlas
operation was read-only against the canonical P2 archive and wrote to the
isolated output root recorded in `results/forecast_trajectory_manifest.json`.

## Fixed rendering contract

- CRS: EPSG:4326.
- Focal extent: longitude -107.5 to -96.0; latitude 24.0 to 33.0.
- Focal cell count: 1,689 canonical cells.
- Figure 3 historical map weeks: 2026-W17, W22, W27, W32, W37; h=1.
- Figure 1 uses one named domain-color mapping in both the full and focal panels.
- Figure 3 occurrence and expected-count surfaces use shared light-low/dark-high sequential scales.
- Prediction/support surfaces are rendered with `geom_tile`; boundary layers are rendered after tiles with `geom_sf`.
- North arrows and scale bars are retained on map panels.

The machine-readable contract is `results/rendering_contract.json`.

## Figure 1 — Domain and framework

Output: `figures/main_candidates/figure_01_domain_framework_corrected.svg`
and `.png`.

Panels A and B now use the same `Mexico` and `U.S.-to-40N` colors, including
both classes in the focal inset. Tracked study-state boundaries are layered
above the cell tiles. Panels C and D retain the technical hurdle-structure and
E0 issue-time schematics.

Source: P7C domain plot data, tracked WGS84 boundary derivative, P0 model
freeze, P5A proxy contract, and P6 configuration.

## Figure 3 — Mexico–Texas historical dynamics

Occurrence output:
`figures/main_candidates/figure_03_mexico_texas_occurrence_corrected.svg`
and `.png`.

The five fixed target weeks are shown with one common occurrence-probability
scale. Observed positives are overlaid as small outlined markers. The lower
panel uses the exact descriptive definition `sum(p_occurrence)` and labels it
as the expected number of positive cells.

Expected-count candidate:
`figures/main_candidates/figure_03_mexico_texas_expected_count_corrected_candidate.svg`
and `.png`.

This candidate uses the same weeks, extent, and map geometry, with a common
full-hurdle expected-count scale and the aggregate `sum(expected_count)`. It is
retained for scientific review and is not substituted into the historical
source artifacts.

Source coverage is 1,689 cells per week for each of the five map weeks and the
P7C h=1 focal time-series interval 2026-W17 through 2026-W37.

## Figure 6 — Support and extrapolation

Output: `figures/main_candidates/figure_06_support_extrapolation_corrected.svg`
and `.png`.

Panel A is rebuilt from the complete 10,037-row canonical P4
`representative_support_map.csv` source as `geom_tile`; the prior point-rendered
P4 image is not reused. Panels B–D retain the canonical support proportions,
performance-by-class summaries, and class labels. Support classes remain
`SUPPORTED`, `CAUTION`, and `EXTRAPOLATIVE` and are not confidence intervals,
direct correctness measures, or causal categories.

## Operational forecast trajectory candidate

Output: `figures/main_candidates/forecast_trajectory_issue_W36_candidate.svg`
and `.png`.

The bounded Atlas extract contains 38,847 rows: 33,780 historical h=1 rows
for W17–W36 and 5,067 forecast rows for the single W36 origin and h=1–3
targets W37–W39. The historical series uses observed positive cells,
`sum(p_occurrence)`, observed total count, and `sum(expected_count)`. The
future dashed path uses only the W36-origin prediction fields. Subsequently
observed W37–W39 outcomes are shown separately as audit markers and are not
connected as forecast values.

This is a candidate operational visualization, not a scheduler or a production
deployment. The underlying aggregates are in
`results/plot_data/forecast_trajectory_aggregates.csv`.

## Forecast uncertainty audit

`results/uncertainty_audit.json` records:

`NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS`

The qualified artifacts contain cell-level uncertainty information but no joint
region-level predictive draws or equivalent regional interval representation.
Cell-level interval limits were not summed and independence was not assumed;
therefore no regional ribbon was drawn.

## Supplementary candidate set

The small supplementary set is copied without scientific or plotting-data
changes from the qualified P7C outputs:

- `S1_reliability_curves`
- `S2_frontier_sensitivity`
- `S3_count_diagnostics_reference`
- `S4_proxy_error_support_transitions`

Their provenance is included in `results/figure_source_registry.csv`.

## Visual inspection

Manual visual inspection was performed on PNG previews of Figure 1, the
occurrence Figure 3 candidate, the expected-count Figure 3 candidate, Figure
6, and the W36 trajectory. The final previews showed:

- visible areal prediction/support surfaces;
- boundary lines above surfaces;
- readable week labels and fixed common scales;
- shared Figure 1 domain colors;
- distinct observed and subsequently observed markers;
- a visually separate W36 issuance boundary and W37–W39 forecast path;
- no uncertainty ribbon or implied regional interval.

The only intermediate rendering defects were tile seams from under-sized
center-spacing tiles and Unicode text glyph substitutions; both were corrected
before the final validation run.

## Validation and provenance

Run the focused validator with:

```powershell
& 'C:\Program Files\R\R-4.5.0\bin\Rscript.exe' `
  'analysis/p7d_cartography_forecast/scripts/validate_p7d_outputs.R' `
  'C:\Users\humph173\.codex\worktrees\p7d-cartography-forecast\STGNN'
```

It checks the frozen model hash, P5A/P6 contracts, fixed bbox and map weeks,
1,689-cell focal extraction, complete P4 support source, layer contract,
support categories, forecast origin/horizon alignment, issue-time outcome
separation, aggregate formula equality, source-registry hashes, and the
explicit uncertainty limitation.

The final focused result was `P7D_VALIDATION_PASSED`.

The Atlas extraction manifest records source archive SHA-256
`918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170` and
bounded extract SHA-256
`532a07030afab56c6f0ba65b8381744f26b6b51212daa70886302e02ee5faa9c`.

## Decision

`P7D_CARTOGRAPHY_FORECAST_SUPPORTED_WITH_LIMITATIONS`

The corrected cartographic outputs and bounded forecast trajectory are
supported for scientific review. The remaining limitations are the absence of
a qualified regional uncertainty ribbon, the cartographic-only role of the
boundary derivative, the candidate status of the expected-count map version,
and the fact that the trajectory is descriptive rather than automated
operational deployment.

