# W44 spatial validation and diagnostics design

## Required estimand

Apply P1 fixed-coefficient transfer to the exact W44 candidate. The spatial question is how this one frozen fit transfers across predeclared regions, not how a model refit in a withheld region performs.

Use the canonical 10,037-node, 25 × 25 km Mexico plus established U.S.-footprint domain and existing country/domain region labels. Report regions separately; do not pool sparse strata post hoc. P1 spatial support requires at least two predeclared regions, with both classes where estimable. Spatiotemporal support also requires at least eight ordered weeks, exact week/node joins, and at least two regions.

## Regional and frontier metrics

For each horizon and region, report node-weeks, positives, prevalence, Brier, log loss, ROC-AUC, PR-AUC, calibration intercept/slope, conditional positive-count MAE/RMSE/bias and observed-to-predicted ratio, and full-hurdle expected-count MAE/RMSE/bias. Mark class-dependent metrics not estimable where a class is absent. Retain separate U.S. and northern Mexico–Texas frontier summaries. Assign frontier status from history available through origin T only. Keep previously occupied, previously unoccupied, and newly detected frontier positives distinct.

## Spatial partitions and graph

P1 geographic comparison is the applicable fixed-model assessment. P2 origins preserve geography and are not a spatial holdout. Development folds in config/validation.yaml use an older 16,756-node domain, 5×5-cell blocks, and development-period folds; do not reuse them as W44 validation.

Before reusing a stored region map or adjacency, verify model_node_id order, grid cells, W44 node count, region labels, and graph checksum against the W44 input manifest. If the exact graph is unavailable, reconstruct only with the documented Queen-neighbor rule on the same canonical grid and record its hash. Do not change neighborhood or block definitions.

For uncertainty preserve P1’s 5×5-cell spatial blocks, two-week temporal blocks, and joint space-time resampling (399 replicates, seed 20261029). Do not resample node-week rows as independent.

## Residual spatial autocorrelation

On independent fixed-W44 post-fit predictions, calculate occurrence-residual and positive-count-residual Moran diagnostics on the fixed Queen graph using the deterministic 199-permutation check from the W29 prospective diagnostic. Report graph identity, residual definition, valid nodes, statistic, permutation result, week and region. Apply no new cutoff. W29 I values 0.3087 (occurrence) and 0.2232 (positive count) describe a different fit and are context only.

## Support and extrapolation

Cross-tab occurrence and expected-count metrics by W44 P4 support class and prediction-time frontier class. Preserve denominators and positive counts. Do not suppress EXTRAPOLATIVE areas or merge them into SUPPORTED. Recompute support with W44 training-only references under the existing rules in analysis/p4_uncertainty_extrapolation/p4_prespecification.md.
