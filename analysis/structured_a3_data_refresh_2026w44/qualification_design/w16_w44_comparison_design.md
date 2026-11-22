# W16 versus W44 comparison design

## Current evidence

The frozen W16 model SHA-256 is 8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e. W44 candidate SHA-256 is b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b. Both use the 34-predictor A3 structure and 10,037 revised-domain cells, but fit endpoints and source vintages differ.

Existing W16 P1/P2 outputs are historical holdout/rolling-origin results. W44 full-fit predictions cover observations used for fitting. They do not form a paired independent comparison. Do not compare their in-sample scores or call W44 fitted-period predictions validation.

## Comparison layers

1. **Fitted geographic predictions (descriptive):** score both stored models on the same raw 34-feature matrix, nodes and weeks/scenarios; preserve each model’s stored preprocessing. Compare probability/expected-count surfaces, regional summaries, rank correlations and cellwise changes. Label as fitted-surface changes, not predictive improvement.
2. **Predictor associations:** align coefficients by exact predictor and hurdle component. Report signs and estimates, with uncertainty only if available; transform to common raw-unit or standardized scales using each fit’s stored scaling. These are associations, not causal effects. W16 bootstrap intervals do not estimate W44 uncertainty.
3. **Calibration:** use identical independent target rows/horizons. Report established calibration metrics without fitting/applying recalibration. Training-period calibration is descriptive only.
4. **Predictive performance:** after prospective issuance begins, issue frozen W16 and W44 models on identical timestamps, inputs/proxy, causal history cutoffs, targets, nodes and h=1,2,3. Compare paired Brier, log loss, PR-AUC, calibration, conditional-count error, full expected-count error and hurdle NLL with established target-week/spatial block resampling. Store two forecasts for each exact origin/target/horizon/node key; score only mature complete post-issue outcomes.
5. **Spatial support/extrapolation:** use a common W44 evaluation matrix and each model’s own training-only support reference. Report both flags and raw novelty; W16/W44 flags are not interchangeable.
6. **Training extension versus source revision:** paired frozen W16/W44 forecasts estimate total model-vintage change; they cannot separate added training weeks from historical revisions. If attribution is needed, add one diagnostic W16-cutoff fit on current W44 inputs truncated at W16. Comparing it with W44 isolates adding W17–W44 under the current snapshot. Comparing it with archived W16 reflects a combined source/history contrast. This fit is optional for the paired predictive claim and cannot replace either frozen model.

## Claim boundary

No paired predictive comparison is available yet. Surface, coefficient, optimizer, or training-fit changes do not establish predictive improvement. Accepted historical revisions limit attribution solely to longer training history.
