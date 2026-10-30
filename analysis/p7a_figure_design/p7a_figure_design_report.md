# P7A Manuscript Figure and Table Design Audit

## 1. Objective and boundary

P7A audits the P7 publication package and defines a compact journal-style
figure/table plan. No model fitting, retraining, tuning, recalibration, feature
selection, SHAP, permutation importance, partial dependence, ALE, or
leave-one-predictor-out refitting was performed.

## 2. Canonical state

The audit was run from canonical main `951a556bf0fc6f37d3192c071c1596c4a356d7f3`.
`STRUCTURED_A3`, the P5A `E0_LAST_AVAILABLE` contract, unchanged P4 support
classes, and `P6_OUTPUT_1.0` were verified. The official Atlas freeze verifier
returned `PRODUCTION_MODEL_FREEZE_VERIFIED` with `trains_model=false`.

## 3. Source audit

The retained P2 archive contains 632,331 rows over 10,037 canonical cells,
h=1--3, target weeks 2026-W17--2026-W39, coordinates, observed counts and
positives, occurrence probabilities, expected counts, and frontier labels. The
archive remains on Atlas; row-level predictions were not copied into the
repository.

The P6 replay products retain cell-level support classes for selected replay
windows. Support proportions and existing P4/P7 summaries are source-complete
for a support figure, but a continuous focal support time series is not
source-complete.

## 4. Recommended main figures

1. **Domain and model framework.** Reuse the P7 schematic, add a fixed full-domain
   and focal-crop overlay from the audited Atlas grid, and show the hurdle
   structure, h=1--3 nowcast, and E0 proxy.
2. **Rolling-origin performance across h=1--3.** Combine Brier, AUPRC, and
   compact calibration summaries using P2 values without re-estimation.
3. **Northern Mexico--Texas spatial-temporal behavior.** Use the fixed crop,
   five evenly spaced h=1 maps, and a regional time series of observed positive
   cells plus expected positive-cell burden.
4. **Issue-time environmental proxy validation.** Show paired REALIZED_ENV versus
   E0 differences across h=1--3; do not describe E0 as a future environmental
   forecast.
5. **Predictor associations and stability.** Use signed coefficients with
   explicit scale markers. Present this as association, not importance or
   causality; do not rank all 34 predictors globally.
6. **Support and extrapolation.** Show SUPPORTED/CAUTION/EXTRAPOLATIVE
   proportions and a representative support/novelty display. Move this to the
   supplement if space is constrained, but retain the caveat in the main text.

## 5. Recommended supplementary figures

The recommended supplementary set is: full reliability curves;
frontier-definition sensitivity; count-process diagnostics; and environmental
proxy error/support transitions.

## 6. Recommended tables

Main tables: model/data specification, occurrence performance, count performance,
and environmental proxy comparison. The limitations/operational-interpretation
table is better placed as a supplement or concise text box to avoid duplicating
the Discussion.

## 7. Mexico--Texas focal region

The fixed crop is longitude -107.5 to -96.0 and latitude 24.0 to 33.0 in
EPSG:4326. It contains 1,689 canonical cells spanning the retained domain
regions Mexico and U.S.-to-40N. The h=1 interval is 2026-W17--W37 with 35,469
cell-week rows.

The recommended maps are 2026-W17, W22, W27, W32, and W37, selected evenly
across the interval. The recommended time-series pair is observed positive cells
and expected positive-cell burden `sum_i p_occurrence`. Optional count series are
observed count and `sum_i expected_count`. The first quantity must not be
described as regional risk.

Peak and change-based week rules were audited but are supplement-only because
they use outcomes or prediction transitions and create avoidable visual
selection risk.

## 8. Predictor contribution

The canonical coefficient artifact provides occurrence and positive-count
coefficients for all 34 predictors. Scaling metadata show that continuous
predictors are standardized, while binary imputation/history indicators and
week sine/cosine terms are unscaled or identity-scaled. Raw coefficient
magnitudes are therefore comparable only within the standardized continuous
subset.

Canonical rolling-origin stability summaries are available for four augmented
predictors. The defensible design is a signed association forest with scale
markers and a separate stability inset/table. A global importance ranking is
not supported.

## 9. Panels requiring additional analysis

A final focal map panel requires an authorized Atlas extraction/aggregation of
the retained P2 archive. A complete focal support time series requires
additional retained cell-level support data. Any global predictor-importance
figure requires separate analytic authorization and is out of scope for P7A.

## 10. Artifacts

Machine-readable outputs are in `analysis/p7a_figure_design/results/`:

- `figure_priority.csv`
- `table_priority.csv`
- `panel_source_registry.csv`
- `focal_region_source_audit.csv`
- `mexico_texas_focal_region.json`
- `focal_region_weekly_summary.csv`
- `predictor_contribution_audit.csv`
- `week_selection_options.csv`
- `atlas_source_audit.json`
- `source_artifact_hashes.csv`
- `decision.json`
- `run_metadata.json`

## 11. Decision

`P7A_FIGURE_PLAN_SUPPORTED_WITH_LIMITATIONS`
