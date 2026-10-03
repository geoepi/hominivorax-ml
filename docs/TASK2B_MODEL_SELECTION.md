# Task 2B model selection

Status: Task-2C audit complete; the provisional Task-2B architecture is not
eligible for final-test evaluation. The final 26-week
period, 2026-W04 through 2026-W29, was not scored, mapped, or used for model
selection.

## Candidate set and execution

The comparison includes the Task-2A seasonal climatology and non-spatial
hurdle-regression baselines, `GRU-Hurdle-NB`, and `GConvGRU-Hurdle-NB`.
XGBoost remains omitted because it is unavailable in the validated Atlas
environment. Neural screening used limited width/K/dropout/learning-rate
experiments, followed by a complete finalist evaluation with 20 temporal runs
per model: four rolling folds and five seeds per fold.

The provisional matched configuration carried into Task 2C is:

| Model | Input | Hidden | K | Dropout | Learning rate | Temporal runs |
|---|---:|---:|---:|---:|---:|---:|
| GConvGRU-Hurdle-NB | 24 | 64 | 3 | 0.1 | 0.0003 | 20 |
| GRU-Hurdle-NB | 24 | 64 | — | 0.1 | 0.0003 | 20 |

The representative-fold refinement also tested dropout 0, 0.1, and 0.3 and
learning rates 1e-4, 3e-4, and 1e-3. The complete four-fold comparison above
was the Task-2B screening evidence; the refinement is retained as sensitivity
evidence and was not treated as a final-test result. Task 2C re-evaluated this
architecture under exact joint and limited balanced-loss objectives. The
development classification is **DO NOT ADVANCE**.

## Temporal development metrics

Values below are means over the five seeds in each fold.

| Fold | Model | Joint NLL | PR-AUC | Brier | ZTNB NLL | Positive MAE | Theta |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | GConvGRU | 0.4839 | 0.0264 | 0.1285 | 2.3950 | 2.7324 | 1.3029 |
| 2 | GConvGRU | 0.4254 | 0.0412 | 0.0996 | 2.4063 | 2.8507 | 1.3005 |
| 3 | GConvGRU | 0.3405 | 0.0374 | 0.0683 | 2.3341 | 2.6098 | 1.2982 |
| 4 | GConvGRU | 0.2330 | 0.0299 | 0.0383 | 2.2798 | 2.4614 | 1.2962 |
| 1 | GRU | 0.6947 | 0.0205 | 0.2259 | 2.6773 | 2.7129 | 1.3029 |
| 2 | GRU | 0.6679 | 0.0211 | 0.2089 | 2.5255 | 2.7711 | 1.3005 |
| 3 | GRU | 0.6151 | 0.0184 | 0.1866 | 2.3473 | 2.5420 | 1.2983 |
| 4 | GRU | 0.5613 | 0.0086 | 0.1709 | 2.2645 | 2.4263 | 1.2964 |

Across all 20 temporal runs, GConvGRU achieved joint NLL 0.3707 (SD
0.1050), PR-AUC 0.0337 (SD 0.0268), Brier 0.0837, positive-count MAE 2.6636,
and fitted theta 1.2995. The matched GRU achieved joint NLL 0.6347 (SD
0.0738), PR-AUC 0.0171 (SD 0.0100), Brier 0.1981, positive-count MAE 2.6131,
and theta 1.2995. GConvGRU was better on joint likelihood, occurrence
discrimination, calibration loss, and all-node-week error; the GRU had a small
positive-count MAE advantage.

Task-2A baselines remain the reference minimum: hurdle-regression PR-AUC was
0.3638, 0.3699, 0.2935, and 0.0817 across folds 1–4; seasonal PR-AUC was
0.0202, 0.0238, 0.0194, and 0.0121. Neural occurrence discrimination is
therefore still below the non-spatial regression baseline in this short
development run, even though the graph model improves markedly over the
matched recurrent comparator.

## Spatial and combined validation

The selected configuration was evaluated using the persisted five spatial
folds. Held-out nodes remained in the known graph and retained covariates, but
their response targets were excluded from fitting; this is transductive
fixed-graph validation, not prediction for entirely unseen geography.

| Regime | Model | Joint NLL | PR-AUC | Brier | All-cell MAE |
|---|---|---:|---:|---:|---:|
| Spatial | GConvGRU | 0.131301 | 0.029636 | 0.015478 | 0.159951 |
| Spatial | GRU | 0.236145 | 0.024903 | 0.036447 | 0.368532 |
| Combined | GConvGRU | 0.261841 | 0.030806 | 0.041187 | 0.343681 |
| Combined | GRU | 0.528472 | 0.027992 | 0.142734 | 0.687721 |

The completed spatial run was job `20840127`; corrected metric scoring was job
`20841217`. Spatial GConvGRU PR-AUC ranged from 0.023043 to 0.037521 across
the five held-out blocks, with negative Brier skill in every block. Combined
GConvGRU temporal-fold mean PR-AUC ranged from 0.013955 to 0.041871 and its
Brier skill remained negative in every fold.

## Calibration and count diagnostics

Reliability tables use adaptive probability bins and are stored in the run
manifests. For GConvGRU, the 20-run mean calibration intercept was -3.0495 and
the mean calibration slope was 0.6796; the corresponding GRU values were
-5.7481 and -3.6040. Positive-count calibration tables, conditional means,
MAE/RMSE, weekly observed-versus-predicted totals, and positive-node summaries
are persisted for every run.

The learned global theta was finite in every run, with GConvGRU mean 1.2995
(SD 0.0026). There were zero non-finite-gradient events. Training used
13-week contiguous TBPTT, 52-week environmental warm-up, and global gradient
clipping at 1.0. The selected GConvGRU runs averaged 57.9 seconds and matched
GRU runs averaged 30.9 seconds on the A100 MIG smoke/training environment.

## Ablations

Single-fold development-only ablations were run with the GConvGRU finalist
settings. Removing livestock fields and indicators produced joint NLL 0.5714,
PR-AUC 0.0488, and positive-count MAE 2.7154. Removing calendar features
produced joint NLL 0.6202, PR-AUC 0.1118, and positive-count MAE 2.7292.
These are diagnostic comparisons, not causal attribution and not final-test
results.

## Task-2C decision and remaining issues

The GConvGRU remained better than the matched GRU on the main joint and Brier
metrics, but it did not approach the non-spatial hurdle regression. Under exact
joint loss its temporal means were PR-AUC 0.018855, Brier 0.048030, Brier skill
-1.5286, joint NLL 0.279639, and positive-count MAE 2.6231. The balanced
λ=0.10 sensitivity improved PR-AUC to 0.031656 but had worse Brier and joint
NLL, with negative Brier skill in all folds. The exact-loss GConvGRU also had
mean predicted probability 0.1702 against prevalence approximately 0.0191.

The global-dispersion ZTNB model was numerically stable, but occurrence
calibration and discrimination remain inadequate. The development decision is
**DO NOT ADVANCE**. Final-test evaluation, threshold selection, production
prediction rasters, and further neural architecture expansion remain deferred.

## Provenance

Successful development jobs and post-processing jobs are recorded in
`STGNN-output/manifests/task2b/task2b_manifest.json`. The corrected source
smoke tests passed for the analytic likelihood, both recurrent model types,
masking, data contracts, and final-test guard. A transient V100 submission
(`20839795`) was rejected by the installed PyTorch build because it supports
SM80/SM89 rather than V100 SM70; no output from that attempt is included.
