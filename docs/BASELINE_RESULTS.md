# Task 2A statistical baselines

Baseline results were calculated only on the four development validation folds in SLURM job `20839532`. No final-test predictive metrics were calculated.

## Response distribution

The development period contains 1,792,892 node-weeks, 25,563 positive node-weeks, and 1,767,329 zero node-weeks. Positive counts have mean 4.0272, variance 18.9411, median 2, maximum 72, and variance/mean 4.7033. The frequency table is persisted in `diagnostics/response_distribution.json`; this supports negative-binomial overdispersion diagnostics relative to Poisson, without independently selecting the later primary model.

## Development metrics

The seasonal baseline estimates occurrence prevalence and conditional positive counts by ISO week-of-year using training data only. The non-spatial hurdle baseline uses all 12 environmental predictors, five completed livestock densities, five imputation indicators, and the two calendar features, with fold-specific transformations/scaling and no coordinates, node identity, or response lags.

| Fold | Model | Log loss | Brier | PR-AUC | ROC-AUC | Positive MAE | Positive RMSE | All-node-week MAE |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Seasonal | 0.1026 | 0.0185 | 0.0202 | — | — | — | 0.0963 |
| 1 | Hurdle regression | 0.0649 | 0.0151 | 0.3638 | 0.9634 | 3.5954 | 6.6030 | 0.0876 |
| 2 | Seasonal | 0.1171 | 0.0225 | 0.0238 | — | — | — | 0.1313 |
| 2 | Hurdle regression | 0.0798 | 0.0181 | 0.3699 | 0.9291 | 3.4056 | 5.5268 | 0.1125 |
| 3 | Seasonal | 0.1079 | 0.0212 | 0.0194 | — | — | — | 0.1383 |
| 3 | Hurdle regression | 0.0811 | 0.0178 | 0.2935 | 0.9019 | 2.7177 | 4.1759 | 0.1057 |
| 4 | Seasonal | 0.0713 | 0.0132 | 0.0121 | — | — | — | 0.0956 |
| 4 | Hurdle regression | 0.0715 | 0.0139 | 0.0817 | 0.8596 | 2.5418 | 3.7678 | 0.0893 |

The fitted hurdle-regression negative-binomial dispersion estimates were 0.3307, 0.4124, 0.4533, and 0.4518 for folds 1–4. Reliability data and a dependency-free SVG plot are in `baselines/reliability_data.csv` and `baselines/reliability_fold1.svg`. Weekly observed/predicted totals and positive-node summaries are stored in each fold JSON.

XGBoost was operationally omitted because the validated Atlas Python environment does not provide the `xgboost` package. The main environment was not altered to install it.
