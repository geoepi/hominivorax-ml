# P7B Science-First Figure Generation Prespecification

## Scope

Generate science-review figures, compact tables, technical captions, and
provenance from canonical P0--P7 artifacts. No model fitting, retraining,
tuning, recalibration, feature selection, or new predictor-importance method
is permitted.

## Canonical contract

- Model: `STRUCTURED_A3`
- Frozen model SHA-256: `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`
- Environmental proxy: `E0_LAST_AVAILABLE`
- Horizons: h=1, h=2, h=3
- Support classes: `SUPPORTED`, `CAUTION`, `EXTRAPOLATIVE`
- Focal CRS: EPSG:4326
- Focal bbox: longitude -107.5 to -96.0; latitude 24.0 to 33.0
- Focal cells: 1,689
- Focal h=1 target interval: 2026-W17 through 2026-W37
- Map weeks: 2026-W17, W22, W27, W32, W37

## Figure rules

1. Figure 1 uses the canonical domain/focal crop and P7 model schematic.
2. Figure 2 uses P2 horizon metrics and calibration results without
   re-estimation.
3. Figure 3 uses only the bounded Atlas extraction. Maps share one extent,
   projection, and legend scale. The primary time series is observed positive
   cells versus `sum_i p_occurrence`, labeled expected number of positive cells.
4. Figure 3 also generates a full expected-count map candidate and count-time
   series candidate without selecting between them for performance reasons.
5. Figure 4 uses P5A paired proxy-minus-realized results and does not imply
   that future environmental conditions are constant.
6. Figure 5 displays signed coefficients with scale categories. It does not
   sort all predictors into a global importance ranking. Stability is shown
   only where canonical stability records exist.
7. Figure 6 uses unchanged P4/P5A/P6 support definitions. No missing support
   class is approximated.

## Atlas extraction contract

Read only the P2 `rolling_origin_predictions.parquet` archive. Filter before
export to the exact focal bbox, h=1, and target weeks 2026-W17--W37. Retain
only canonical cell ID, coordinates, target/origin week, horizon, observed
occurrence/count, p_occurrence, conditional count, expected count, and frontier
fields required for the figure. Do not copy the full P2 archive.

## Output and reproducibility

Every panel receives a source-registry row with source path/hash, fields,
filters, transformations, output path, and output hash. Underlying plotted data
must be deterministic across two generation runs. Vector metadata differences
are acceptable only when underlying plotted-data hashes are identical.

## Writing boundary

Only technical figure titles, labels, legends, concise captions, and technical
notes may be generated. No manuscript Results, Discussion, Methods,
Introduction, abstract, or submission narrative is produced.
