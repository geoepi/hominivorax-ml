# P7D Prespecification

## Scope

P7D changes only cartographic rendering and descriptive operational visualization. The frozen STRUCTURED_A3 model, E0_LAST_AVAILABLE proxy, P4 thresholds, focal region, and selected historical map weeks remain unchanged. No model fitting, refitting, recalibration, feature importance method, or new uncertainty analysis is permitted.

## Fixed map contract

- CRS: EPSG:4326.
- Focal region: longitude -107.5 to -96.0; latitude 24.0 to 33.0.
- Focal cells: 1,689.
- Historical map weeks: 2026-W17, W22, W27, W32, W37.
- Historical map horizon: h=1.
- Boundary source: Atlas `study_states` GeoPackage, rendered through the tracked WGS84 WKT derivative.
- Layer order: prediction/support tiles first; transparent jurisdictional boundaries second.
- Map annotations: north arrow and scale bar retained on map panels.

## Rendering rules

- Figure 1 uses one shared named domain-color mapping for full-domain and focal panels.
- Figure 3 occurrence and expected-count surfaces use shared light-to-dark sequential scales across all five weeks.
- Observed detections remain visible using small high-contrast markers.
- Figure 6 uses canonical P4 support classifications rendered as `geom_tile`; the prior point-rendered image is not reused.
- Support categories remain SUPPORTED, CAUTION, and EXTRAPOLATIVE and are not interpreted as confidence intervals or correctness measures.

## Operational forecast candidate

- Issue week: 2026-W36.
- Future targets: W37, W38, W39.
- Forecast horizons: h=1, h=2, h=3.
- Historical observed series: h=1 rows for W17-W36, using the corresponding prior-week origins.
- Future forecast series: rows from the single W36 origin for h=1-3.
- Occurrence aggregate: observed positive cells and `sum(p_occurrence)`.
- Count aggregate: observed total count and `sum(expected_count)`.
- Future realized outcomes, if displayed, are labeled subsequently observed and are never connected as if available at issuance.
- The trajectory figure remains a candidate and does not replace historical Figure 3.

## Uncertainty rule

No regional uncertainty ribbon will be drawn unless an existing qualified artifact contains joint region-level predictive draws or an equivalent region-level uncertainty representation. Cell-level interval limits will not be summed and independence will not be assumed. If no qualified regional representation exists, the output will explicitly record `NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS`.

## Validation rules

- Freeze verifier must return `PRODUCTION_MODEL_FREEZE_VERIFIED`.
- Figure 1 must use a shared domain palette and show both focal domain classes.
- Figure 3 must use tile rendering, fixed weeks/bounds, post-tile boundaries, north arrow, scale bar, light low values, and readable week labels.
- Figure 6 must use canonical support classes, areal tiles, post-tile boundaries, north arrow, and scale bar.
- Forecast targets must match W36 -> W37/W38/W39 exactly.
- Forecast data must contain no future observations in the forecast construction fields.
- Plotted-data files and source registry must be deterministic across repeated generation.

