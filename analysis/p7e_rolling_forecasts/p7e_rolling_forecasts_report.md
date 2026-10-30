# P7E — Rolling-Origin Forecast Visualization

## 1. Objective and boundary

P7E is a bounded, science-facing visualization and aggregation phase. It uses
the canonical P2 rolling-origin prediction archive and does not fit, refit,
retune, recalibrate, or modify STRUCTURED_A3, the E0 proxy, support thresholds,
or uncertainty specifications.

## 2. Canonical source and extraction

The source archive is the P2 rolling-origin Parquet archive at
`/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/predictions/rolling_origin_predictions.parquet`.
The recorded source SHA-256 is
`918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170`.
Extraction was performed on Atlas using the validated Python environment and
the authorized WSL/Ubuntu `atlas-ssh` route.

The focal region is fixed in EPSG:4326 at longitude -107.5 to -96.0 and
latitude 24.0 to 33.0, containing 1,689 canonical cells. The extracted source
subset contains 106,407 cell-level rows: 21 origins (2026-W16 through
2026-W36), three horizons, and 1,689 cells per origin/horizon. Aggregation
produces 63 forecast rows. The available complete observed history is
2026-W17 through 2026-W39.

## 3. Prespecified quantities

For each issue week and horizon, observed positive-cell burden is
`sum(observed_positive > 0)` and expected positive-cell burden is
`sum(p_occurrence)`. Forecast error is expected minus observed. The count
candidate uses `sum(observed_count)` and `sum(expected_count)` with the same
origin/horizon contract.

The primary occurrence display uses target-week points connected within each
issue week. All 21 threads are retained. The deterministic highlighted subset
is W16, W20, W24, W28, W32, and W36. Horizon is encoded consistently by color
and point shape. Issue-week markers are retained as light vertical guides.

## 4. Generated figures

### Occurrence figure

`figures/figure_rolling_occurrence_forecasts.svg` and its PNG preview contain:

* Panel A: observed and expected positive-cell burden across target weeks;
* Panel B: signed forecast error by issue week and horizon;
* Panel C: signed-error distributions by horizon.

### Count candidate

`figures/figure_rolling_count_forecasts_candidate.svg` and its PNG preview use
the corresponding observed and expected total-count quantities. This remains
a candidate visualization for scientific review rather than a change to the
count model.

## 5. Uncertainty and interpretation boundary

The canonical source does not support a regional uncertainty ribbon for this
P7E display. The rendering contract records
`NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS`, and no uncertainty band is
drawn. The figures show retrospective rolling-origin predictions and observed
outcomes; they do not constitute a new prospective environmental forecast
analysis.

## 6. Validation and reproducibility

The focused validator confirms exact origins, horizons, target chronology,
1,689-cell coverage, aggregation formulas, registry completeness, figure
hashes, no uncertainty ribbon, and absence of model-fitting calls. The
generator was run twice; underlying plotted-data CSV hashes were identical.
See `results/validation_results.json`, `results/plot_data_hashes_run1.txt`,
and `results/plot_data_hashes_run2.txt`.

## 7. Visual QA

PNG previews were inspected at rendered resolution. The occurrence figure is
readable as a three-panel forecast-thread display with a common burden scale
and explicit horizon encodings. The count figure is retained as a candidate;
its larger count scale and dense thread structure warrant review before any
manuscript placement.

## 8. Decision

P7E_ROLLING_FORECAST_FIGURE_SUPPORTED_WITH_LIMITATIONS

The occurrence visualization is complete, source-traceable, deterministic,
and reproducible. Limitations are the absence of canonical regional
uncertainty information and the status of the count-burden display as a
candidate visualization.
