# P1 existing-validation audit

## Purpose

This audit was completed before new P1 computation. It records which existing
artifacts can be reused and which must be excluded because they do not use the
exact P0 frozen artifact.

## Existing coverage

| Existing artifact | Coverage | Status for P1 |
|---|---|---|
| `analysis/structured_a3_evaluation/results/overall_metrics.csv` | Historical exposed holdout, 2026-W17–W29 | Reusable as historical context only; not an independent claim |
| `analysis/structured_a3_evaluation/results/geographic_metrics.csv` | Historical Mexico and United States summaries, 2026-W17–W29 | Reusable as historical context only; not a spatial holdout |
| `analysis/structured_a3_evaluation/results/weekly_metrics.csv` | Historical weekly summaries, 2026-W17–W29 | Reusable as historical context only |
| `analysis/structured_a3_evaluation/results/evaluation_period_provenance.csv` | Development, exposed holdout, and ineligible later periods | Reusable as the temporal eligibility boundary |
| `analysis/structured_a3_prospective_diagnostics/` | W30–W39 prospective diagnostic archive | Not promoted directly: its manifest identifies `STRUCTURED_A3_FULLFIT`, fit through W29, with coefficients different from P0 `STRUCTURED_A3` |
| `analysis/structured_a3_fullfit/` | Full-fit production products | Not used for P1 inference or model identity |

## Required P1 gap

The prior W30–W39 archive contains valuable protected-data provenance and
outcome joins, but it is not evidence for the exact P0 candidate. P1 therefore
reconstructs the validated W30–W39 predictor matrix from the refresh artifacts,
scores it with `analysis/structured_a3_evaluation/results/final_a3_model.json`,
and retains the prior archive only for its canonical week/node outcome join and
coordinate/region fields.

## Boundary decisions

- Historical W17–W29 remains `HISTORICAL EXPOSED HOLDOUT`.
- P1 begins strictly after 2026-W16 and uses the latest validated refresh
  available in the repository/Atlas archive: W30–W39.
- No evaluation-period scaling, imputation, coefficient update, calibration
  write-back, threshold selection, or refit is permitted.
- Geographic transfer uses canonical Mexico versus United States/domain-region
  labels. It does not use random rows.
- Frontier classes use causal prior-history indicators and are reported
  descriptively when support is sparse.
- Uncertainty uses ordered temporal blocks and spatial raster blocks; individual
  row bootstrap is not used.

