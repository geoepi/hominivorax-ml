# Task 2G — Frozen Hurdle-Current terminal evaluation

## Scope and governance

Task 2G evaluates the pre-selected `Hurdle-Current` model on the future holdout
2026-W17 through 2026-W29. The model was fit once on all development responses
from 2025-W01 through 2026-W16. No terminal target values were accessed before
the freeze manifest was written, and no augmented candidate was scored.

The work was performed on `feature/terminal-evaluation`, based on Task 2F HEAD
`5e58f4be2d5c60a77c8bb4e6af47f10e35b19a1e`. The freeze fit was recorded in
commit `d20e947c92a67a55565a4152689d9927014270b6`.

The event order was:

| Event | UTC timestamp / job |
| --- | --- |
| Model freeze and manifest write | Slurm 20844222; completed 2026-10-03 23:44 UTC |
| Terminal unlock | 2026-10-03T23:45:32+00:00; Slurm 20844224 |
| Terminal metric scoring | 2026-10-03T23:45:35+00:00; Slurm 20844224 |
| Reporting recovery | Slurm 20844226; completed after the scoring job |

The first scoring job completed all terminal predictions and metrics but stopped
at map rendering because the Atlas environment does not provide `matplotlib`.
The recovery job generated dependency-free SVG maps and final checksums from
the persisted terminal predictions. It did not refit, rescore, recalibrate, or
change any model result.

## Frozen fit

The model is the exact 24-predictor Hurdle-Current specification documented in
`docs/FINAL_MODEL_SPECIFICATION.md`. The occurrence and positive-count fits
both reported successful convergence with finite coefficients. The final global
ZTNB theta was `0.9063853224209942`; the training fit contained 682,516 rows and
9,546 positive node-weeks.

The freeze manifest checksum is:

```text
d5787cf89e593dc1f70aa9cb60f6ca7f34160f63dac8dd12df491f7157a0895f
```

Source observation SHA: `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e`.
Dataset manifest SHA: `ce60e713ccaf1651f0a9724bd7209c52ee83ee6efa4613a9ffc3b2882b8c74b7`.

## Full-domain terminal results

| Metric | Result |
| --- | ---: |
| Node-weeks | 130,481 |
| Positive node-weeks | 5,302 |
| Prevalence | 0.0406343 |
| Mean predicted probability | 0.0153385 |
| Bernoulli NLL | 0.1455740 |
| Brier score | 0.0365188 |
| Brier skill vs development prevalence null | 0.0799745 |
| PR-AUC | 0.2123061 |
| PR-AUC / prevalence | 5.2248 |
| ROC-AUC | 0.8856069 |
| Calibration intercept | 0.4283459 |
| Calibration slope | 0.7643934 |
| Joint hurdle NLL | 0.2104402 |
| Positive-count ZTNB NLL | 1.5963431 |
| Positive-count MAE | 1.9947477 |
| Positive-count RMSE | 2.5817951 |
| All-node-week MAE | 0.1204586 |
| All-node-week RMSE | 0.6048605 |
| Observed total detections | 11,673 |
| Predicted expected total detections | 7,009.4789 |
| Predicted occurrence probability mass | 2,001.3862 |

The Brier null is fixed from the full development prevalence (`0.0139865`),
not estimated from terminal prevalence.

## Regional results

| Region | Node-weeks | Positive node-weeks | Prevalence | Mean p | Brier | Brier skill | PR-AUC | ROC-AUC | Joint NLL | Positive MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full revised domain | 130,481 | 5,302 | 0.0406343 | 0.0153385 | 0.0365188 | 0.0799745 | 0.2123061 | 0.8856069 | 0.2104402 | 1.9947 |
| Mexico | 40,612 | 5,272 | 0.1298138 | 0.0391976 | 0.1163944 | 0.0789994 | 0.2460353 | 0.7577394 | 0.6605934 | 2.0020 |
| United States | 89,869 | 30 | 0.0003338 | 0.0045565 | 0.0004228 | 0.1870480 | 0.0003857 | 0.5959416 | 0.0070149 | 0.7130 |

The U.S. PR-AUC is only about 1.155 times U.S. prevalence, and its ROC-AUC is
near chance despite a positive Brier skill value; this is why the U.S. result is
not interpreted as strong transfer.

## U.S. transfer and first detections

The terminal U.S. subset contains 89,869 node-weeks, 30 positive node-weeks, 24
unique positive nodes, and 40 recorded detections. Detections occur in seven
weeks, 2026-W23 through 2026-W29. The first retained U.S. positive is in
2026-W23.

The complete positive-case rank table is
`us_transfer/terminal_us_positive_ranks.csv`. It reports the week, node, state,
coordinates, observed count, and percentile among U.S. nodes and all revised-
domain nodes for that week. Only 6.67% of positive U.S. cases were at or above
the 75th percentile among U.S. nodes. Examples include W23 Texas cases at
within-U.S. percentiles 68.30 and 70.95, while the strongest listed cases reach
82.09 in W24 and 83.19 in W26.

| Week | U.S. max p | U.S. mean p | U.S. p95 | Observed positive U.S. nodes | Observed U.S. detections |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-W17 | 0.02753 | 0.000983 | 0.004218 | 0 | 0 |
| 2026-W18 | 0.01976 | 0.001638 | 0.007233 | 0 | 0 |
| 2026-W19 | 0.01884 | 0.001280 | 0.006214 | 0 | 0 |
| 2026-W20 | 0.02956 | 0.001479 | 0.007871 | 0 | 0 |
| 2026-W21 | 0.05243 | 0.004756 | 0.021064 | 0 | 0 |
| 2026-W22 | 0.06194 | 0.006053 | 0.029066 | 0 | 0 |
| 2026-W23 | 0.07567 | 0.004801 | 0.024744 | 3 | 4 |
| 2026-W24 | 0.06756 | 0.005711 | 0.024491 | 6 | 8 |
| 2026-W25 | 0.09774 | 0.008298 | 0.043840 | 2 | 2 |
| 2026-W26 | 0.04668 | 0.004732 | 0.019376 | 6 | 12 |
| 2026-W27 | 0.04702 | 0.004765 | 0.018044 | 5 | 5 |
| 2026-W28 | 0.07591 | 0.007253 | 0.027305 | 3 | 3 |
| 2026-W29 | 0.06904 | 0.007485 | 0.028291 | 5 | 6 |

The rise in U.S. predicted risk during W21-W22 preceded the first recorded U.S.
positive in W23, but the positive-case ranks and U.S. discrimination are mixed.
The pre-specified interpretation is **WEAK / AMBIGUOUS NORTHWARD TRANSFER**.

## Latitude progression

The full fixed-band output is `metrics/terminal_latitude_metrics.csv`. The
pattern is a strong south-to-north gradient rather than uniform risk. For
example, in W23 the mean probabilities were 0.14288, 0.06204, 0.00557,
0.00721, and 0.00176 in the `<20N`, `20-25N`, `25-30N`, `30-35N`, and `35-40N`
bands, respectively. The corresponding positive node-week counts were 195,
216, 19, 1, and 0. This is a descriptive evaluation diagnostic only.

## Calibration and count diagnostics

Adaptive-bin reliability data for the full domain, Mexico, and the U.S. are in
`metrics/terminal_calibration.csv`. The full-domain terminal calibration
intercept is 0.4283 and slope is 0.7644. In the highest full-domain adaptive
bin, mean predicted probability was 0.11052 versus observed prevalence 0.22770.
The U.S. calibration fit is unstable because there are only 30 positive
node-weeks; its intercept is -6.963 and slope is 0.155. No post-hoc calibration
was performed.

Among terminal positive node-weeks, observed counts averaged 2.2016 and the
predicted conditional positive mean averaged 3.2793. The count bias (predicted
minus observed) was +1.0777, with MAE 1.9947 and RMSE 2.5818. Extreme observed
counts are retained in `metrics/terminal_extreme_positive_counts.csv` as
descriptive diagnostics; dispersion was not refit.

## Development-versus-terminal comparison

| Metric | Development four-fold minimum | Development mean | Development four-fold maximum | Terminal | In development range? |
| --- | ---: | ---: | ---: | ---: | --- |
| Brier skill | 0.02637 | 0.05314 | 0.09856 | 0.07997 | Yes |
| PR-AUC | 0.17816 | 0.22738 | 0.26096 | 0.21231 | Yes |
| Joint NLL | 0.10969 | 0.13220 | 0.16158 | 0.21044 | No; worse |
| Positive MAE | 1.42037 | 2.37180 | 3.11982 | 1.99475 | Yes |

## Interpretation

The frozen model **PARTIAL GENERALIZATION**. It retains positive full-domain
discrimination and Brier skill, and Mexico performance remains useful, but
joint NLL and calibration deteriorate beyond the development-fold range. The
U.S. diagnostic is separately classified as **WEAK / AMBIGUOUS NORTHWARD
TRANSFER**.

These classifications are descriptive summaries, not a composite selection
score. The primary model was not changed after terminal scoring, and the
secondary Hurdle-Spatiotemporal model was not scored.

## Artifacts, maps, and limitations

The complete output is under
`/project/disease_ecology/STGNN-output/terminal_evaluation/`, including the
required parquet, JSON, CSV, manifests, checksums, and SVG evaluation maps.
Maps use a common probability scale across the requested weeks and include
observed positive cells; focused U.S./northern-Mexico maps cover W22-W24.

The first scoring wrapper's missing plotting dependency was an infrastructure
limitation, repaired after scoring with dependency-free SVG reporting from the
persisted predictions. This did not alter the frozen model, terminal targets,
metrics, or predictions. The U.S. positive sample is small, recorded detection
is an observation process rather than a direct biological-spread observation,
and the evaluation does not establish transmission or spread mechanisms.
