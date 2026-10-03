# Task 2E — Revised-domain baseline results

Status: completed on Atlas in development-only Slurm job `20844173`. The
baseline outputs are under
`/project/disease_ecology/STGNN-output/revised_model_data/validation/`.
No predictive metric was calculated for the terminal holdout.

## Evaluation contract

The comparison contains three baselines:

1. a training-period prevalence null;
2. a training-only seasonal climatology by ISO week-of-year;
3. a current-week exact-joint hurdle baseline.

The hurdle baseline uses the 24 current-week predictors documented in the
production dataset. Fold-specific means and scales are learned on training
weeks only; `log1p` is applied only to the five livestock densities, while
imputation indicators and calendar sine/cosine features remain on their
natural scales. The occurrence component is logistic and the positive-count
component is a zero-truncated negative-binomial model. The reported hurdle
loss is the exact joint occurrence-plus-positive-count NLL.

## Temporal development results

The prevalence null and seasonal climatology are the Brier reference for each
fold. The current-week hurdle model reduced Brier score in every validation
fold and had a mean Brier skill of 0.0531.

| Fold | Hurdle Brier | Brier skill | Joint hurdle NLL | Positive MAE | Positive RMSE | ROC-AUC | PR-AUC |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.01534 | 0.0264 | 0.1423 | 2.4346 | 4.5032 | 0.9055 | 0.2469 |
| 2 | 0.01627 | 0.0986 | 0.1152 | 3.1198 | 4.0056 | 0.9591 | 0.2610 |
| 3 | 0.01650 | 0.0349 | 0.1097 | 2.5124 | 2.8758 | 0.9530 | 0.1782 |
| 4 | 0.02664 | 0.0527 | 0.1616 | 1.4204 | 2.0262 | 0.9339 | 0.2235 |

Both hurdle components converged successfully in all four temporal folds after
increasing the iteration ceiling to 500. The fold-specific dispersion estimates are 1.6265,
1.4074, 1.3240, and 1.0895.

## Stratified diagnostics

The current-week hurdle Brier skill is positive in each seasonal stratum on
average: summer 0.0415, fall 0.0580, winter 0.0386, and spring 0.0551. The
latitude-band diagnostics are persisted in `task2e_latitude_metrics.csv`; the
lowest observed skill is in the 20–25°N bands, while the sparse northern bands
have very high apparent skill because they contain few positive node-weeks.

Mexico retains positive temporal Brier skill in all four folds (0.0252, 0.0959,
0.0300, and 0.0494). The U.S. temporal subsets contain zero positive
node-weeks in every development validation fold. Their PR-AUC, ROC-AUC, and
calibration slope/intercept are therefore explicitly marked undefined/not
informative; their near-one Brier-skill values must not be interpreted as
validated U.S. discrimination.

Development-only five-fold spatial validation over the first 68 weeks also
remained positive, with full-domain Brier skills 0.0718, 0.1203, 0.1011,
0.0628, and 0.1123 (mean 0.0937). Mexico-specific spatial diagnostics are
reported; U.S. class-degenerate metrics remain flagged rather than interpreted.

Coefficient tables, reliability data, per-fold predictions, regional and
seasonal tables, latitude diagnostics, and U.S. case diagnostics are written
alongside the machine-readable `task2e_baseline_results.json`.

## Advancement screen and holdout rule

The predefined development evidence screen is **ADVANCE**: optimization was
stable, mean temporal Brier skill was positive, Fold 4 was non-catastrophic,
and spatial development skill was positive. This is a baseline evidence
classification only. Task 2E does not fit GRU/GConvGRU or other advanced
models, does not add structured lags or spatial-neighborhood predictors, and
does not score the terminal holdout. The manifest records
`terminal_holdout_metrics_calculated: false`.
