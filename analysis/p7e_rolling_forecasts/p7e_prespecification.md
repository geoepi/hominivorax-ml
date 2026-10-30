# P7E prespecification

## Scope

P7E is a bounded visualization and aggregation phase. It uses the canonical
P2 rolling-origin prediction archive without refitting or modifying
`STRUCTURED_A3`, `E0_LAST_AVAILABLE`, support thresholds, uncertainty rules, or
any P0-P7D scientific artifact.

## Source and spatial contract

- Source: canonical P2 `rolling_origin_predictions.parquet`.
- Focal CRS: EPSG:4326.
- Focal bounding box: longitude -107.5 to -96.0; latitude 24.0 to 33.0.
- Expected focal cells: 1,689.
- Origins: 2026-W16 through 2026-W36, inclusive.
- Horizons: h=1, h=2, h=3.
- Expected forecast rows after regional aggregation: 63.

## Quantities

For each origin T and horizon h, occurrence burden is the sum of the 1,689
cell-level `p_occurrence` values. Observed burden is the number of focal cells
with `observed_positive > 0` at the target week. Signed error is
`expected_positive_cells - observed_positive_cells`; absolute error is its
absolute value. The count candidate uses the corresponding sums of
`expected_count` and `observed_count`.

The observed-history series uses the earliest complete target-week coverage
available in the P2 archive. If W10-W16 are absent, the display starts at the
earliest complete week and does not fabricate a pre-origin history.

## Plot design

Panel A shows the observed regional burden and all 21 distinct three-point
forecast threads. Forecasts are plotted at target weeks only (Option B): each
thread is grouped by its issue origin and is not connected to another origin.
Issue weeks are indicated with faint vertical markers. Horizons use a single
blue family, with h=1 darkest, h=2 intermediate, and h=3 lightest. Origins
W16, W20, W24, W28, W32, and W36 are deterministically emphasized while all
other origins remain visible.

Panel B shows signed forecast error by issue week with a horizontal zero line.
Panel C shows the signed-error distribution by horizon using the same 21
origins per horizon. No uncertainty ribbon is drawn.

The count version uses the same design as a technical candidate and is not
promoted to a scientific headline by P7E.

## Leakage and validation rules

- Every origin/horizon must map to exactly one target week, with target equal
  to T+h.
- Every origin/horizon must contain all 1,689 focal cells.
- Future observed outcomes may be used only for retrospective comparison and
  error calculation, never to construct forecast values.
- No later-origin prediction may be substituted for an earlier-origin thread.
- No cell-level uncertainty intervals may be summed or converted into a
  regional ribbon.
- Plotting-data generation must be deterministic across repeated runs.

## Decision rule

`P7E_ROLLING_FORECAST_FIGURE_SUPPORTED` is used if the occurrence figure,
chronology, aggregation, leakage, and deterministic-data checks pass and the
threads remain readable. `P7E_ROLLING_FORECAST_FIGURE_SUPPORTED_WITH_LIMITATIONS`
is used if the occurrence figure is scientifically sound but visual density or
count interpretability remains a limitation. `P7E_ROLLING_FORECAST_FIGURE_NOT_SUPPORTED`
is used if source coverage, chronology, leakage prevention, or reproducibility
fails.
