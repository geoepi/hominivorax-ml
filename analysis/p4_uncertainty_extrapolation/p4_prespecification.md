# P4 Uncertainty and Extrapolation Assessment — Prespecification

This document is committed before P4 result generation. P4 is an evaluation
and diagnostic exercise for the immutable `STRUCTURED_A3` production
candidate. It does not change the P0 artifact, predictor order, response,
training horizon, objective, penalty, fixed theta, optimizer, domain, or
canonical P2 predictions.

## Reference state and data boundary

- Frozen model: `STRUCTURED_A3`.
- Frozen model SHA-256:
  `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.
- Starting canonical main/P3 merge:
  `7aba3f3527324a13349d4355170d6ac81dcb8376`.
- P2 archive: 632,331 immutable rows from the 21 origins
  `2026-W16`–`2026-W36`, horizons 1–3.
- Environmental training reference: all 10,037 canonical nodes for
  `2025-W01`–`2026-W16` (160,592 node-weeks), using the existing A3 feature
  cache and exact 34-feature order.
- Evaluation targets: the canonical P2 rolling-origin archive only. Future
  outcome columns are used for performance evaluation, never for scaling,
  novelty thresholds, support classification, or bootstrap target selection.

## A. Environmental support and novelty

The P2 feature cache is the only predictor source. The training reference is
flattened over the 16 training weeks and all nodes. The existing A3
`standardize` implementation is used once with that reference: scaled
predictors use the training mean and standard deviation; indicator and
calendar predictors retain their frozen unscaled state. A non-finite or zero
training standard deviation is replaced by the implementation's fixed scale
of one. Evaluation rows are never used to estimate a mean, scale, quantile,
or threshold.

For every predictor, retain the training center, scale, minimum, maximum,
1st/5th/95th/99th percentiles, missingness, and transformation/scaling state.
For every P2 row, retain:

- nearest-neighbor Euclidean distance in the standardized 34-dimensional
  frozen predictor space;
- count of predictors below the training minimum, above the training maximum,
  outside the 1–99% interval, and outside the 5–95% interval;
- the predictor names causing each range exceedance;
- maximum absolute standardized deviation.

The nearest-neighbor reference is the complete training population. Training
support thresholds use the leave-one-out nearest-neighbor distance
distribution: `SUPPORTED` is at or below the training 95th percentile,
`CAUTION` is above the 95th and at or below the 99th percentile, and
`EXTRAPOLATIVE` is above the 99th percentile. The production diagnostic flag
is deterministic and input-only:

- `EXTRAPOLATIVE` if any predictor is outside the training min/max or the
  nearest-neighbor distance is above the training 99th percentile;
- `CAUTION` if any predictor is outside the training 1–99% interval or the
  nearest-neighbor distance is above the training 95th percentile;
- `SUPPORTED` otherwise.

These thresholds are fixed from training support and are not selected using
P2 performance. Continuous novelty is retained through the distance and
range counts, and summarized using fixed training distance bins (<=50th,
50–75th, 75–90th, 90–95th, 95–99th, and >99th percentiles).

## B. Predictive uncertainty and count intervals

Occurrence uncertainty is represented by the canonical Bernoulli predictive
variance `p(1-p)`. It is not called parameter uncertainty.

The count component uses the exact frozen zero-truncated negative-binomial
distribution with `theta = 0.7018903965556372` and the canonical predicted
positive-count mean. For each P2 row, calculate the conditional-positive
mean, variance, median, and central 50%, 80%, and 95% predictive intervals.
The full hurdle distribution adds a point mass at zero with probability
`1-p_occurrence`; its expectation and variance are calculated exactly from
the hurdle mixture, and its quantiles are calculated from the same exact
mixture. No Gaussian approximation is used.

Coverage is reported for h=1, h=2, and h=3 at nominal 50%, 80%, and 95%
levels, for all rows and for observed-positive rows. It is additionally
stratified by environmental support class and prediction-time frontier class
where sample sizes are nonzero. Interval width and empirical coverage are
reported together.

## C. Model/parameter uncertainty bootstrap

The canonical prediction remains primary. Model uncertainty is a bounded
diagnostic refit using the exact A3 fitter: 34 predictors, frozen feature
order, penalty `0.01`, fixed theta, exact joint hurdle objective, and
L-BFGS-B settings. There is no feature selection, tuning, recalibration, or
alternative model.

Dependence is preserved by resampling complete training weeks
`2025-W01`–`2026-W16` with replacement; all 10,037 nodes in a sampled week
remain together. The base seed is `20261029`, with replicate seed equal to
`20261029 + replicate_id`. Request 100 successful replicates and launch at
most 120 deterministic replicate slots. A replicate is successful only when
both exact A3 components converge and finite predictions are produced. Every
slot is recorded as successful or failed with its failure cause; failures are
not silently dropped. A result with fewer than 80 successful replicates is a
P4 material uncertainty warning.

Bootstrap prediction targets are fixed before fitting: at most 200 rows per
combination of support class, frontier group (frontier/established),
U.S./other region, and horizon. Rows are selected by stable sort on
origin-week, target-week, and node ID. The target manifest is saved and the
same targets are used for every replicate. For occurrence probability,
conditional positive count, and full expected count, retain canonical value,
bootstrap mean, standard deviation, and 2.5%, 25%, 50%, 75%, and 97.5%
quantiles. Bootstrap means never replace canonical predictions.

Diagnostics retain requested, successful, and failed counts; failure causes;
component convergence; objective values; iteration counts; coefficient norms;
and coefficient instability summaries. Aggregation is ordered by replicate
ID and is independent of Slurm completion order.

## D. Performance versus support

Using the immutable P2 outcomes and predictions, report by horizon and
support class:

- occurrence Brier score, calibration intercept/slope, AUPRC, and AUROC where
  estimable;
- conditional positive-count MAE and bias;
- full-hurdle MAE and bias;
- predictive interval coverage and mean width;
- bootstrap SD of occurrence probability and full expected count for the fixed
  uncertainty target set.

The same metrics are summarized over the fixed continuous novelty bins. The
frontier interaction uses the four prespecified groups: established and
frontier crossed with supported versus low support (`CAUTION` or
`EXTRAPOLATIVE`). Sparse groups are reported without pooling and are not
overinterpreted. U.S./regional summaries report row counts, positives,
novelty, support proportions, and performance where estimable; P4 does not
claim to resolve sparse U.S. outcome support.

## E. Limitations and decision rules

Track at minimum sparse frontier support, sparse U.S./regional outcome
support, positive-count/count-process bias, retrospective environmental
availability, lack of a true refitted spatial holdout, and numerical
stability. Each is classified after results as one of:
`BETTER_CHARACTERIZED`, `PARTIALLY_EXPLAINED_BY_EXTRAPOLATION`,
`ROBUST_LIMITATION`, `NOT_ADDRESSABLE_IN_P4`, or
`MATERIAL_UNCERTAINTY_FAILURE`. A support flag identifying a limitation does
not resolve it.

Use one decision marker exactly:

- `P4_UNCERTAINTY_SUPPORT_SUPPORTED`;
- `P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS`;
- `P4_UNCERTAINTY_SUPPORT_NOT_SUPPORTED`.

`SUPPORTED` requires reproducible support metrics, stable uncertainty, and
reasonable interval behavior without a new material failure. `SUPPORTED WITH
LIMITATIONS` is used when support is characterizable but weak regions,
imperfect coverage, or explicit caution/extrapolation flags remain.
`NOT_SUPPORTED` is reserved for unstable uncertainty, catastrophic intervals,
unreliable support characterization, or extreme ordinary-condition model
uncertainty.
