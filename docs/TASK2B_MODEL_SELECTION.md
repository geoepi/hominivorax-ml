# Task 2B model selection

Status: verified development-only comparison on Atlas. The final 26-week
period, 2026-W04 through 2026-W29, was not scored, mapped, or used for model
selection.

## Candidate set and execution

The comparison includes the Task-2A seasonal climatology and non-spatial
hurdle-regression baselines, `GRU-Hurdle-NB`, and `GConvGRU-Hurdle-NB`.
XGBoost remains omitted because it is unavailable in the validated Atlas
environment. Neural screening used limited width/K/dropout/learning-rate
experiments, followed by a complete finalist evaluation with 20 temporal runs
per model: four rolling folds and five seeds per fold.

The selected matched configuration is:

| Model | Input | Hidden | K | Dropout | Learning rate | Temporal runs |
|---|---:|---:|---:|---:|---:|---:|
| GConvGRU-Hurdle-NB | 24 | 64 | 3 | 0.1 | 0.0003 | 20 |
| GRU-Hurdle-NB | 24 | 64 | — | 0.1 | 0.0003 | 20 |

The representative-fold refinement also tested dropout 0, 0.1, and 0.3 and
learning rates 1e-4, 3e-4, and 1e-3. The complete four-fold comparison above
is the selection evidence; the refinement is retained as sensitivity evidence
and was not treated as a final-test result.

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
| Spatial | GConvGRU | 0.3347 | 0.0213 | 0.0712 | 0.5761 |
| Spatial | GRU | 0.5484 | 0.0085 | 0.1630 | 0.7917 |
| Combined | GConvGRU | 0.5655 | 0.0536 | 0.1641 | 0.7742 |
| Combined | GRU | 0.6490 | 0.0181 | 0.2021 | 0.7701 |

Spatial GConvGRU PR-AUC ranged from 0.0164 to 0.0245 across the five held-out
folds. Combined GConvGRU PR-AUC ranged from 0.0386 to 0.0745.

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

## Selection rationale and remaining issues

The GConvGRU finalist is preferred because it consistently improves joint
likelihood, occurrence Brier score/PR-AUC, and spatial/combined joint metrics
over the matched non-graph GRU across all four temporal folds. Performance is
still weak relative to the Task-2A hurdle-regression occurrence baseline,
especially in later temporal regimes, so this result is a development finding
and not evidence of production superiority. The global-dispersion ZTNB model
was numerically stable, but count calibration remains imperfect. Final-test
evaluation, threshold selection, production prediction rasters, and neural
architecture expansion remain deferred.

## Provenance

Successful development jobs and post-processing jobs are recorded in
`STGNN-output/manifests/task2b/task2b_manifest.json`. The corrected source
smoke tests passed for the analytic likelihood, both recurrent model types,
masking, data contracts, and final-test guard. A transient V100 submission
(`20839795`) was rejected by the installed PyTorch build because it supports
SM80/SM89 rather than V100 SM70; no output from that attempt is included.
