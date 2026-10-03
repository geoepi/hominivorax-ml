# Hurdle-loss comparison

Task 2C compares the old balanced auxiliary loss with the exact observation-
level joint hurdle negative log likelihood. All results are development-only.

## Definitions

For recorded count `y`, occurrence probability `p`, underlying NB mean `mu`,
and global dispersion `theta`:

```text
L_balanced = mean(Bernoulli NLL) + lambda * mean(ZTNB NLL | y > 0)
L_joint    = mean(-log(1-p), y = 0;
                  -log(p) - log(ZTNB(y | mu, theta)), y > 0)
```

The conditional count expectation is computed as

```text
E[Y | Y > 0] = mu / (1 - NB(0 | mu, theta))
```

and the hurdle expectation is `p * E[Y | Y > 0]`. The model uses one learned
global `theta = softplus(raw_theta) + epsilon`.

## Stage-1 screening

The fixed architecture was hidden width 64, K=3 for GConvGRU, dropout 0.1,
learning rate 3e-4, 12 epochs, folds 2 and 4, and two fixed seeds. The
authoritative evaluator was applied after checkpoint replay.

| Model | Objective | Mean PR-AUC | Mean Brier | Mean Bernoulli NLL | Mean joint NLL | Mean ZTNB NLL | Mean positive MAE |
|---|---|---:|---:|---:|---:|---:|---:|
| GConvGRU | exact joint | 0.024826 | 0.039035 | 0.194439 | 0.249421 | 2.973212 | 2.595165 |
| GConvGRU | balanced λ=1 | 0.026703 | 0.078579 | 0.311782 | 0.354974 | 2.363965 | 2.637184 |
| GConvGRU | balanced λ=0.25 | 0.039789 | 0.052074 | 0.237582 | 0.283205 | 2.493612 | 2.584421 |
| GConvGRU | balanced λ=0.10 | 0.043010 | 0.044571 | 0.214039 | 0.262110 | 2.623835 | 2.576796 |
| GRU | exact joint | 0.034266 | 0.128001 | 0.440036 | 0.495619 | 3.017542 | 2.607978 |
| GRU | balanced λ=1 | 0.015559 | 0.172210 | 0.533995 | 0.577997 | 2.397399 | 2.605829 |
| GRU | balanced λ=0.25 | 0.019531 | 0.151888 | 0.492229 | 0.539107 | 2.552141 | 2.561414 |
| GRU | balanced λ=0.10 | 0.024064 | 0.141202 | 0.469366 | 0.518549 | 2.676444 | 2.561053 |

Stage 1 shows that lowering the auxiliary count weight improves GConvGRU
occurrence behavior, while exact joint training gives the best GConvGRU Brier
and joint NLL in this screen. Both exact joint and balanced λ=0.10 therefore
advanced; the comparison is not selected from PR-AUC alone.

## Stage 2 temporal results

Stage 2 used four folds and five seeds for exact joint loss and balanced
λ=0.10. Means over the 20 runs per model/objective were:

| Model | Objective | PR-AUC | Brier | Brier skill | Bernoulli NLL | Joint NLL | ZTNB NLL | Positive MAE | Fold-4 PR-AUC | Fold-4 Brier skill |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GConvGRU | exact joint | 0.018855 | 0.048030 | -1.5286 | 0.223752 | 0.279639 | 2.9009 | 2.6231 | 0.018780 | -0.6265 |
| GConvGRU | balanced λ=0.10 | 0.031656 | 0.054374 | -1.8601 | 0.244078 | 0.293409 | 2.5688 | 2.5996 | 0.036382 | -0.8455 |
| GRU | exact joint | 0.034607 | 0.160511 | -7.6678 | 0.509438 | 0.568000 | 3.0381 | 2.6437 | 0.027805 | -8.1028 |
| GRU | balanced λ=0.10 | 0.029036 | 0.172452 | -8.3770 | 0.534955 | 0.587011 | 2.7056 | 2.5908 | 0.024020 | -9.5722 |

Exact joint loss is the preferred formulation for likelihood-based reporting:
it gives the GConvGRU the best Brier/joint-NLL tradeoff and respects the
observation-level hurdle likelihood. The λ=0.10 sensitivity has better
GConvGRU PR-AUC and positive-count ZTNB NLL, but its Brier skill is negative in
all four folds and it does not approach the non-spatial hurdle baseline.

The final preferred exact-loss GConvGRU still has mean predicted probability
0.1702 against validation prevalence approximately 0.0191, calibration
intercept -5.083, calibration slope -0.899, and negative Brier skill in every
fold. This is a calibration failure, not a threshold-selection issue.

## Spatial and combined exact-loss diagnostics

The completed spatial/combined job (`20840127`) was scored by corrected audit
job `20841217`. The audit processed all 50 existing run manifests after a
Level-1 fix removed an unintended temporal-only filter. Results are pooled
over the five spatial folds, or over the twenty combined runs as indicated.

| Regime | Model | Joint NLL | PR-AUC | Brier | Brier skill | Bernoulli NLL | ZTNB NLL | Positive MAE |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Spatial | GConvGRU | 0.131301 | 0.029636 | 0.015478 | -0.106614 | 0.092969 | 2.677573 | 2.560903 |
| Spatial | GRU | 0.236145 | 0.024903 | 0.036447 | -1.628782 | 0.199629 | 2.551959 | 2.550327 |
| Combined | GConvGRU | 0.261841 | 0.030806 | 0.041187 | -1.193889 | 0.201971 | 3.086878 | 2.645127 |
| Combined | GRU | 0.528472 | 0.027992 | 0.142734 | -6.821763 | 0.472750 | 2.881304 | 2.587131 |

The exact-loss GConvGRU was better than the matched GRU in both regimes on
joint likelihood, Brier score, and all-cell error. Nevertheless, Brier skill
remained negative, and both neural models remained below the frozen
non-spatial hurdle regression. The spatial and combined evidence therefore
does not authorize advancement or final-test evaluation.

## Advancement classification

**DO NOT ADVANCE.** Neither neural formulation meets the Task-2C advancement
criteria. The preferred GConvGRU remains substantially worse than the frozen
non-spatial hurdle regression (PR-AUC 0.277434, Brier 0.016224, joint NLL
0.119783), and both neural formulations have negative Brier skill in every
temporal fold. Spatial and combined exact-loss diagnostics are still run as
development evidence, but they cannot authorize final-test evaluation.

No final-test metric is permitted in this task.
