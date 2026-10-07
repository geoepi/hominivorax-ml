# Task 2C metric audit

Status: development-only audit on Atlas. The final-test interval
2026-W04 through 2026-W29 remains sealed; no predictive metric, prediction
array, map, or residual diagnostic has been calculated for it.

## Scope and comparability

The audit was performed from the Task-2C branch on the frozen Task-2A node
universe, weeks, targets, graph, and feature contract. Every development
result now passes through `python/task2c_metrics.py`, which uses
`sklearn.metrics.average_precision_score` for PR-AUC, the same explicit target
masks, clipped Bernoulli log loss, Brier score, ROC-AUC, adaptive quantile
reliability bins, calibration intercept/slope, positive-count metrics, and the
same ZTNB post-hoc scoring calculation.

The historical Task-2A reliability display used equal-width bins whereas the
Task-2B display used adaptive bins. That presentation difference does not
change the core occurrence metrics, but the historical calibration displays
are not treated as directly comparable. Historical Task-2A count/joint scores
also used an untruncated NB implementation; the audit relabels those as
post-hoc ZTNB scores and records the score family explicitly.

Task-2A and Task-2B occurrence metrics are otherwise comparable: they use the
same 16,756-node universe, the same four temporal validation masks, the same
recorded-detection target, the same denominator, and average precision rather
than trapezoidal PR-curve area.

## Fold-specific null and baseline results

The table reports validation prevalence, training prevalence, PR-AUC, Brier,
Bernoulli NLL, and joint hurdle NLL from the authoritative evaluator.

| Fold | Validation prevalence | Training prevalence | Constant PR-AUC | Constant Brier | Seasonal PR-AUC | Hurdle-regression PR-AUC | Hurdle-regression Brier | Hurdle-regression joint NLL |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.018684 | 0.009645 | 0.018684 | 0.018417 | 0.020247 | 0.363780 | 0.015125 | 0.111617 |
| 2 | 0.022839 | 0.011453 | 0.022839 | 0.022447 | 0.023752 | 0.369914 | 0.018082 | 0.135093 |
| 3 | 0.021586 | 0.013351 | 0.021586 | 0.021188 | 0.019418 | 0.293530 | 0.017823 | 0.130863 |
| 4 | 0.013387 | 0.014527 | 0.013387 | 0.013209 | 0.012107 | 0.082514 | 0.013866 | 0.101560 |

The non-spatial hurdle regression is the relevant minimum benchmark. Its mean
PR-AUC is 0.277434, mean Brier score 0.016224, mean Bernoulli NLL 0.074363,
and mean joint hurdle NLL 0.119783. The constant-prevalence mean Brier is
0.018815 and mean Bernoulli NLL is 0.096743.

## Existing Task-2B neural re-score

The 20-run finalist sets were re-scored without retraining. The old balanced
loss produced the following means over four folds and five seeds:

| Model | Bernoulli NLL | Brier | Brier skill | PR-AUC | ROC-AUC | Joint NLL | ZTNB NLL | Positive MAE | Mean predicted p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GConvGRU-Hurdle-NB | 0.325564 | 0.083657 | -3.383240 | 0.033728 | 0.611546 | 0.370716 | 2.353779 | 2.663581 | 0.258034 |
| GRU-Hurdle-NB | 0.587574 | 0.198076 | -9.829239 | 0.017117 | 0.362454 | 0.634745 | 2.453620 | 2.613086 | 0.437577 |

The graph model improved over the matched GRU, but both neural occurrence
heads were poor relative to the non-spatial hurdle regression. In particular,
the probability heads were grossly overpredictive.

## Probability diagnostics

Mean predicted probability among validation positives versus observed zeros
was:

| Model | Fold 1 | Fold 2 | Fold 3 | Fold 4 |
|---|---:|---:|---:|---:|
| GConvGRU positive minus zero | +0.0063 | +0.0052 | +0.0129 | +0.0293 |
| GRU positive minus zero | -0.0171 | -0.0224 | -0.0267 | -0.0473 |

The GConvGRU probabilities were high nearly everywhere and only weakly ranked
positives. The GRU reversed the ranking in every fold. Adaptive reliability
tables and the full p05/p25/median/p75/p95/p99 distributions are persisted in
the authoritative manifest and compact prediction files under the external
Task-2C output root.

## Loss audit and remediation

The prior objective is retained and explicitly named
`balanced_multitask_loss`:

```text
mean(Bernoulli NLL over eligible node-weeks)
+ lambda * mean(ZTNB NLL over positive eligible node-weeks)
```

It is not the exact joint hurdle likelihood. The new
`exact_joint_hurdle_nll` averages the observation-level hurdle NLL, using
`-log(1-p)` for zeros and `-log(p) - log(ZTNB(y))` for positives. The two
implementations are tested to agree with the prevalence-weighted component
identity. The stable ZTNB calculations use analytic mean/dispersion
parameterization and log1mexp normalization.

The authorized Stage-1 comparison used folds 2 and 4, two seeds, the fixed
hidden-64/K-3/dropout-0.1/learning-rate-3e-4 architecture, and four objectives:
exact joint, balanced λ=1, balanced λ=0.10, and balanced λ=0.25. Exact joint
loss and balanced λ=0.10 advanced to the authorized four-fold/five-seed Stage
2; λ=1 and λ=0.25 did not advance.

Authoritative run-level results are stored outside Git in
`STGNN-output/validation/task2c/authoritative_task2c.csv`, with prediction
arrays in `STGNN-output/predictions/task2c/`.

## Four-fold/five-seed remediation

Stage 2 used the fixed hidden-64/K-3/dropout-0.1/learning-rate-3e-4
architecture. Exact joint GConvGRU means were PR-AUC 0.018855, Brier 0.048030,
Brier skill -1.5286, Bernoulli NLL 0.223752, joint NLL 0.279639, ZTNB NLL
2.9009, and positive-count MAE 2.6231. Balanced λ=0.10 produced PR-AUC
0.031656, Brier 0.054374, Brier skill -1.8601, Bernoulli NLL 0.244078,
joint NLL 0.293409, ZTNB NLL 2.5688, and positive-count MAE 2.5996.

The exact-loss GConvGRU was selected for spatial/combined development
diagnostics because it has the better likelihood and Brier tradeoff. Its mean
predicted probability was 0.1702 versus validation prevalence approximately
0.0191; calibration intercept was -5.083 and slope -0.899. Brier skill was
negative in every temporal fold, including Fold 4. The matched exact-loss GRU
was worse on Brier and joint likelihood (means 0.160511 and 0.568000).

The neural models therefore remain substantially below the frozen non-spatial
hurdle regression, whose mean PR-AUC is 0.277434, mean Brier 0.016224, mean
Bernoulli NLL 0.074363, and mean joint NLL 0.119783. Task 2C classification is
**DO NOT ADVANCE**. No final-test evaluation is authorized.

## Spatial and combined validation

The completed spatial job was `20840127`; its scoring job was rerun as
`20841217` after correcting a Level-1 audit-filter bug that had discarded
non-temporal regimes. The corrected audit scored all 50 existing runs:
five spatial folds and twenty combined spatiotemporal runs for each matched
model. No model was retrained and the final-test interval remained locked.

| Regime | Model | Joint NLL | PR-AUC | Brier | Brier skill | Bernoulli NLL | ROC-AUC | ZTNB NLL | Positive MAE | All-cell MAE |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Spatial | GConvGRU | 0.131301 | 0.029636 | 0.015478 | -0.106614 | 0.092969 | 0.742656 | 2.677573 | 2.560903 | 0.159951 |
| Spatial | GRU | 0.236145 | 0.024903 | 0.036447 | -1.628782 | 0.199629 | 0.723752 | 2.551959 | 2.550327 | 0.368532 |
| Combined | GConvGRU | 0.261841 | 0.030806 | 0.041187 | -1.193889 | 0.201971 | 0.646520 | 3.086878 | 2.645127 | 0.343681 |
| Combined | GRU | 0.528472 | 0.027992 | 0.142734 | -6.821763 | 0.472750 | 0.629410 | 2.881304 | 2.587131 | 0.687721 |

Spatial GConvGRU PR-AUC ranged from 0.023043 to 0.037521 across held-out
blocks, with Brier skill negative in all five blocks. Combined GConvGRU
temporal-fold means were PR-AUC 0.013955, 0.028453, 0.038947, and 0.041871
for Folds 1-4, with Brier skill -2.9022, -0.9689, -0.4836, and -0.4208.
The matched GRU was worse on Brier and joint likelihood in both regimes.
These results provide the required transductive spatial and combined
development evidence but do not change the **DO NOT ADVANCE** decision.

## Guard and interpretation

All audit and remediation run manifests set
`final_test_predictive_metrics_calculated` to false. The existing development
mode guard refuses final-test scoring. The audit does not change target
semantics, the canonical node domain, the graph, features, validation splits,
response-lag policy, or count family.
