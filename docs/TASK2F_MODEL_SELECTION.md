# Task 2F — Structured Revised-Domain Model Selection

## Decision

The development-only result is **HOLD / AMBIGUOUS**. The locked 24-feature
`Hurdle-Current` model remains the preferred candidate at penalty 0. The best
augmented candidate by mean temporal Brier skill is
`Hurdle-Spatiotemporal`, but it does not satisfy every pre-specified material-
consistency guardrail. No candidate is advanced to terminal-holdout scoring.

The prior GConvGRU status remains **DO NOT ADVANCE**.

## Temporal development comparison

Values below are from the four predefined temporal folds. Brier skill is relative
to the fold-specific null comparator; joint NLL is the joint hurdle NLL.

| Candidate | Features | Selected penalty | Mean Brier skill | Fold 4 Brier skill | Mean joint NLL | Mean PR-AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Hurdle-Current | 24 | 0 | 0.05314 | 0.05270 | 0.13220 | 0.22738 |
| Hurdle-Spatial | 41 | 0.01 | 0.08676 | 0.05296 | 0.11391 | 0.24430 |
| Hurdle-Temporal | 60 | 0.01 | 0.09078 | 0.04582 | 0.11355 | 0.23569 |
| Hurdle-Spatiotemporal | 77 | 0.01 | 0.09825 | 0.04755 | 0.11337 | 0.24262 |

Relative to `Hurdle-Current`, the best augmented temporal candidate improves mean
Brier skill by `0.04511`, mean joint NLL by `-0.01882`, and mean PR-AUC by
`0.01524`, but its Fold 4 Brier-skill change is `-0.00515`. This is just below
the required `-0.005` worst-fold guardrail. `Hurdle-Temporal` also misses that
guardrail (`-0.00687`). `Hurdle-Spatial` has a positive Fold 4 change
(`+0.00027`) but was not the best augmented candidate selected for the full
spatial/combined validation stage.

## Spatial and combined validation

The full spatial and combined development space-time checks were intentionally
limited to `Hurdle-Current` and `Hurdle-Spatiotemporal`. On the spatial holdout
nodes, mean Brier skill was `0.09368` for the current model and `0.11429` for
the spatiotemporal model. In combined validation, mean Brier skill was `0.06959`
for the current model and `0.10461` for the spatiotemporal model. These gains do
not override the failed temporal worst-fold guardrail.

Regional summaries include seasonal, latitude-stratified, and degenerate-region
handling. The U.S. regional slices without observed positives report PR-AUC and
ROC-AUC as undefined rather than manufacturing a score. The Mexico `<25N`
training versus `>=25N` development evaluation is recorded as a development-only
northward-transfer proxy; it is not terminal validation.

## Selection rule

There is no composite score. An augmented candidate must meet every guardrail:

- mean temporal Brier-skill improvement at least `0.005`;
- Fold 4 Brier-skill change at least `-0.005`;
- mean joint hurdle NLL change no worse than `+0.005`;
- mean PR-AUC change at least `-0.01`;
- spatial Brier skill no worse than the current model by more than `0.005`; and
- combined Brier skill no worse than the current model by more than `0.005`.

If multiple candidates pass, the larger mean Brier-skill improvement is preferred,
with the smaller feature set as the tie-breaker. The recorded result is HOLD /
AMBIGUOUS because augmented candidates show positive average evidence but no
candidate satisfies the complete guardrail set.

## Reproduction and holdout audit

The Task 2F implementation reproduces the Task 2E current-model fold metrics with
maximum absolute difference `9.71e-17`, below the recorded tolerance `1e-4`.
The comparison is stored in
`diagnostics/task2e_baseline_reproduction.json`.

The final manifest records:

- `terminal_holdout_metrics_calculated: false`; and
- `terminal_us_positive_outcomes_inspected: false`.

The complete machine-readable decision is in
`manifests/task2f_model_selection.json`; all development metrics are under the
structured output root described in
`docs/STRUCTURED_REVISED_FEATURES.md`.
