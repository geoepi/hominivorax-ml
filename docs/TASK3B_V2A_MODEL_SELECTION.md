# Task 3B — V2-A Model Development and Selection

V2-A was evaluated as a historical development experiment. It models recorded detections conditional on current covariates and prior recorded detections; it does not estimate occupancy, detection probability, abundance, or biological dispersal. The former V1 terminal period is historical evaluated data, not an unseen test.

## Decision

- V2-A decision: **V2-A ADVANCES**
- Latitude ablation: **LATITUDE REDUNDANT**
- Selected penalties: `{"M0": 0.0, "M1": 0.01, "M2": 0.01}`
- Predictive models outside V2-A fitted: **NO**
- Neural models fitted: **NO**

Selection used Folds 1–4 only. M0 remained fixed at penalty 0. M1 and M2 used only the authorized grid and were selected by mean Folds 1–4 joint hurdle NLL, then Brier skill and smaller penalty as tie-breakers. Folds 5–6 are historical pseudo-prospective and non-independent.

## Development summary — Folds 1–4

| Model | Mean joint NLL | Mean Brier skill | Mean PR-AUC | Mean positive-count MAE |
|---|---:|---:|---:|---:|
| M0 | 0.132177 | 0.0531563 | 0.227395 | 2.3718 |
| M1 | 0.0775795 | 0.366593 | 0.456112 | 2.39983 |
| M2 | 0.0768659 | 0.366663 | 0.456162 | 2.24894 |

## Historical pseudo-prospective summary — Folds 5–6

| Model | Mean joint NLL | Mean Brier skill | Mean PR-AUC | Mean positive-count MAE |
|---|---:|---:|---:|---:|
| M0 | 0.201236 | 0.0920386 | 0.228364 | 1.83086 |
| M1 | 0.144861 | 0.330335 | 0.444092 | 1.71527 |
| M2 | 0.14373 | 0.330488 | 0.444278 | 1.24125 |

## First-ever positive localization — Folds 1–4

| Model | Median percentile | Fraction >=75th | Fraction >=90th |
|---|---:|---:|---:|
| M0 | 91.8842 | 0.893106 | 0.596087 |
| M1 | 93.471 | 1 | 0.853943 |
| M2 | 93.471 | 1 | 0.853943 |

The full case-level ranks, first-ever versus recurrent count summaries, calibration by prior-history state, front-distance strata, geographic transfer diagnostics, coefficient stability, and collinearity are in `STGNN-output/v2_model/metrics/`.

## V1 reproduction

The M0 reproduction is recorded in `metrics/v1_reproduction.csv`; the absolute joint-NLL and Brier-skill differences against the persisted Task 2F reference are expected to be within numerical tolerance. The response contract uses the immutable V1 target array. A small source-classification versus V1-target reconciliation is documented in the manifest because the earlier classification table and preflight assignment differ for a small number of response cells.

## Validation policy

Development specification-freeze date: **2026-10-03**. No currently available 2025–2026 observations qualify as a genuinely unseen V2 test. Observations arriving after this date form the first genuinely independent V2 evaluation period; V2-A remains a development-frozen candidate, not a validated final production model.
