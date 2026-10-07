# Task 2F — Structured Revised-Domain Features

## Scope and data contract

Task 2F evaluates structured spatial and antecedent environmental augmentations of
the locked Task 2E hurdle baseline. The analysis uses the revised-domain production
arrays with 81 response weeks and 10,037 nodes. Only development weeks 0:67
(2025-W01 through 2026-W16) are read into model-fitting and scoring arrays. The
terminal holdout (2026-W17 through 2026-W29; indices 68:80) remains sealed.

The source dataset SHA-256 is
`a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e`.
The Task 2F implementation is on branch `feature/structured-revised-domain` at
commit `238ccad7af6d732ff63b427ded12837db6a48fac`.

The 24-feature Task 2E contract, response definition, count family, hurdle
likelihood, persisted queen graph, and four validation folds are unchanged.

## Feature construction

### Spatial features

The persisted binary queen graph has 10,037 nodes and 77,614 directed edges. The
operator is

\[
S = D_{self}^{-1}(A + I),
\]

where the focal-node self-loop is included in the denominator. Each of the 12
environmental predictors receives a current-week local mean. The five livestock
density predictors are transformed as `log1p` before the local mean is computed.
The five livestock imputation indicators and the two calendar terms are not
spatially averaged. Isolated nodes therefore retain their own value, and a
constant field remains constant; the recorded maximum constant-field error is
`2.22e-16`. There are three isolated nodes.

This produces 17 spatial additions and a 41-feature `Hurdle-Spatial` candidate.

### Antecedent features

For each of the 12 environmental predictors, the implementation adds:

- the immediately preceding week (`lag1`);
- the mean of the previous four weeks (`prev4mean`); and
- the mean of the previous 13 weeks (`prev13mean`).

Antecedents use only prior covariate weeks and the existing 185-week history. No
response lags are used. The earliest response week is 2025-W01, and its
antecedents are obtained from the history rather than from future response or
covariate values. The 36 antecedent features are ordered in three blocks: all
12 `lag1` features, all 12 `prev4mean` features, then all 12 `prev13mean`
features.

This produces a 60-feature `Hurdle-Temporal` candidate. Combining spatial and
antecedent additions produces the 77-feature `Hurdle-Spatiotemporal` candidate.

| Candidate | Base | Spatial additions | Antecedent additions | Total |
| --- | ---: | ---: | ---: | ---: |
| Hurdle-Current | 24 | 0 | 0 | 24 |
| Hurdle-Spatial | 24 | 17 | 0 | 41 |
| Hurdle-Temporal | 24 | 0 | 36 | 60 |
| Hurdle-Spatiotemporal | 24 | 17 | 36 | 77 |

## Scaling and regularization

Every training/evaluation split computes feature means and standard deviations on
training cells only. The seven binary/calendar base features remain unscaled as
in Task 2E; continuous base, spatial, and antecedent features use training-only
standardization. Zero-variance training features use a unit scale. The L2 grid is
exactly:

`0`, `1e-5`, `1e-4`, `1e-3`, `1e-2`.

The penalty applies to slopes only; intercepts are excluded. The current candidate
is locked at penalty 0 to reproduce Task 2E exactly. Augmented candidates select
their penalty using the four predefined temporal folds, with joint hurdle NLL as
the primary criterion, Brier as the tie-breaker, and the smaller penalty as the
final tie-breaker.

## Validation and provenance outputs

The CPU Slurm entry point is
`hpc/run_task2f_structured.sbatch`. The output root is
`/project/disease_ecology/STGNN-output/revised_model_data/structured/`.

Key outputs are:

- `manifests/task2f_feature_manifest.json` and `diagnostics/task2f_feature_qa.json`;
- `manifests/task2f_selected_penalties.json`;
- `validation/task2f_regularization_grid.csv` and
  `validation/task2f_regularization_summary.csv`;
- `validation/task2f_temporal_metrics.csv`,
  `validation/task2f_seasonal_metrics.csv`,
  `validation/task2f_spatial_metrics.csv`,
  `validation/task2f_combined_metrics.csv`,
  `validation/task2f_latitude_metrics.csv`,
  `validation/task2f_regional_metrics.csv`, and
  `validation/task2f_northward_transfer_proxy.csv`;
- `diagnostics/task2f_coefficients.csv`,
  `diagnostics/task2f_coefficient_family_summary.csv`, and
  `diagnostics/task2f_coefficient_stability.csv`; and
- `manifests/task2f_model_selection.json` and `manifests/task2f_manifest.json`.

Full spatial and combined development space-time validation was limited to the
current candidate and the best augmented candidate by temporal Brier skill, as
specified in the task instructions. No terminal-holdout metrics were calculated,
and no terminal-period U.S. positive outcomes were inspected.
