# Structured A3 prospective failure-mode analysis

Authoritative archive: `STRUCTURED_A3_FULLFIT` prospective run `a3-prospective-corrected-20261017`.
This is a diagnostic-only evaluation. The frozen A3 coefficients, scaling, theta, penalty, predictors, and evaluation period were not changed; no A3 refit, recalibration, feature selection, or A4 fit was performed.

## Executive summary

The analysis covers exactly `2026-W30, 2026-W31, 2026-W32, 2026-W33, 2026-W34, 2026-W35, 2026-W36, 2026-W37, 2026-W38, 2026-W39` (100,370 node-weeks; 4,529 positive node-weeks). Reproduction of the stored full-domain report is `PASS`.
Full-domain prospective performance was ROC-AUC `0.9549`, PR-AUC `0.4258`, Brier skill `0.2944`, and joint hurdle NLL `0.1689`. The full-domain calibration intercept/slope were `-0.0621` / `1.1348`.
The U.S. transfer assessment was based on within-U.S. risk ranks, not full-domain ROC-AUC: the prospective U.S. region contained 12 positive node-weeks, with median positive risk percentile and top-k capture reported in `results/us_risk_ranking.csv`.
Final pre-registered decision: **DEVELOP A4**.

## Decision evidence

- U.S. median positive risk percentile: `99.23`; fraction at or above the 75th percentile: `0.917`; top-10% recall: `0.917`.
- Pooled occurrence-residual Moran's I: `0.3087`; deterministic permutation p-value: `0.0050`.
- Pooled positive-count residual Moran's I: `0.2232`.
- Prospective conditional-count median ratio (predicted/observed): `3.067`.
- Features with more than 10% of prospective rows beyond ±3 frozen training SD: `2`.

## Methods

- Frozen model: `STRUCTURED_A3_FULLFIT`, fit/evaluation horizon ending `2026-W29`, theta `0.7018903965556372`, penalty `0.01`, 34 predictors, 10,037 nodes.
- Prospective observations and predictions were joined by exact `(week, model_node_id)` keys. The required boundary check fails closed unless the weeks are exactly W30-W39.
- Occurrence and hurdle likelihood metrics use the repository evaluator in `python/task2c_metrics.py`. Weekly and strata metrics are descriptive slices; insufficient-class metrics are marked not estimable.
- Calibration uses the established two-parameter logistic calibration convention and is reported diagnostically only; no recalibration parameters are written back to A3.
- Fixed latitude bands are <20N, 20-25N, 25-30N, 30-35N, and 35-40N. Front-distance bins are predeclared in the runner. U.S. rank usefulness requires median positive percentile ≥75, ≥50% of positive node-weeks at ≥75, and top-10% recall ≥50%.
- Spatial diagnostics use the fixed queen graph and deterministic 199-permutation Moran's I checks. Covariate shift uses the frozen training means/SDs, development min/max, and reconstructed 34-predictor matrices; associations are not interpreted causally.

## Results

Authoritative tables:

- `results/metric_reproduction_check.csv`
- `results/prospective_vs_terminal_metrics.csv`
- `results/weekly_metrics.csv` and `results/weekly_trend_summary.csv`
- `results/geographic_strata_metrics.csv`
- `results/us_risk_ranking.csv`
- `results/front_distance_metrics.csv`
- `results/calibration_summary.csv`
- `results/count_process_metrics.csv`
- `results/spatial_residual_summary.csv`
- `results/covariate_shift_summary.csv`
- `results/highest_confidence_false_positives.csv`, `results/highest_confidence_false_negatives.csv`, `results/largest_count_underpredictions.csv`, and `results/largest_count_overpredictions.csv`

Required figures are in `figures/` as 300-DPI PNG and vector PDF files. On Atlas they are rendered by `scripts/render_figures.R` using the validated repository R environment because the project Python venv is intentionally table/scoring focused.

## Failure-mode assessment

See `results/a3_prospective_diagnostic_summary.json` for machine-readable PASS / MINOR CONCERN / MAJOR CONCERN classifications and evidence. Individual records are descriptive examples only and are not causal explanations.

## Provenance and immutability

`results/analysis_manifest.json` records the repository SHA, all input paths and SHA-256 values, model constants, weeks, predictor/node counts, and runtime versions. The analysis reads authoritative Atlas artifacts and writes only to its separate analysis output root; it does not overwrite production or corrected prospective artifacts.

## Reproduction

Use the repository Python bootstrap, then run `python analysis/structured_a3_prospective_diagnostics/scripts/run_diagnostics.py --help`. The production Atlas paths are intentionally passed explicitly; large Atlas data products are not committed to Git.

## Pre-registered comparison thresholds

A change is `SIMILAR` when its absolute change is within the metric-specific thresholds in `results/analysis_manifest.json` or relative change is ≤ 10%; otherwise direction is determined by the metric's stated better/worse direction. Thresholds were fixed before inspecting diagnostic outcomes.
