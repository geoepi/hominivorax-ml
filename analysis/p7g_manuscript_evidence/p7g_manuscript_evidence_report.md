# P7G Manuscript Evidence Completion Report

## 1. Objective

P7G completed four bounded, evaluation-only diagnostics to close manuscript
evidence gaps while preserving the frozen `STRUCTURED_A3` model and all P0–P7F
scientific artifacts. No model fitting, refitting, recalibration, feature
selection, ablation, new spatial cross-validation, or new importance method was
performed.

The prespecification was committed before result-bearing execution:
`cf092e888a6014f627dc7cd452963a5ffb66aeda`.

## 2. Canonical source validation

The canonical P2 archive was read from Atlas with SHA-256
`918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170` and
632,331 rows. The P4 support classification archive was read with SHA-256
`c35bf794fcc882e3ea71bc1a279b90e4f32aeff412a9399f2fb25e383141d058` and the
same row count. The frozen model hash remained
`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.
P2 origins were W16–W36 with h=1–3. Source schemas, duplicate keys, support
join cardinality, node order, and the canonical queen graph were validated.

The required freeze verifier passed before execution and after result
generation. The Atlas job was `21069366`, terminal state `COMPLETED`, elapsed
time 5:51, with approximately 1.19 GB peak resident memory.

## 3. Analysis A — Spatial and temporal dependence

Raw and residual occurrence, positive-count, and full-hurdle count quantities
were calculated using the existing P2/P3/A3 definitions. Spatial summaries use
the canonical queen graph and exact shells 1–4. Temporal summaries use exact
ISO-week lags 1–3 within cell and horizon.

Machine-readable outputs are:

* `results/spatial_dependence.csv`;
* `results/spatial_shell_dependence.csv`;
* `results/temporal_dependence.csv`.

All 72 pooled shell summaries and all 72 pooled temporal/within-cell summary
records were estimable. Raw occurrence association was positive across shells;
occurrence residual association was lower than raw association but remained
positive. This is a diagnostic characterization, not evidence of a new spatial
holdout or an exemption from the existing spatial-support limitations.

## 4. Analysis B — First-recorded detection ranking

First-recorded detections were defined from the leakage-safe P2
`previously_occupied` history and the first eligible positive per cell. Ranking
used `p_occurrence` and, when informative, the existing P2 reference scores.
Top-k fractions were fixed at 1%, 5%, 10%, and 20%, with full-domain and
frontier-relative pools.

Machine-readable outputs are:

* `results/early_warning_topk.csv`;
* `results/first_detection_event_rankings.csv`;
* `results/early_warning_trajectory.csv`;
* `results/early_warning_metadata.json`.

The primary occurrence score was estimable for 860 h=1, 843 h=2, and 826 h=3
first-detection records. Frontier-relative capture was materially higher than
full-domain capture at the same top-ranked fractions, while h=3 capture was
weaker at the most selective fractions. The historical-prevalence and
persistence reference columns were not informative in the retained first-event
frontier subsets and are explicitly marked rather than treated as competing
validated ranking models.

## 5. Analysis C — Predictor dependence and standardized association

The exact frozen 34-predictor order and the P4 reference period
`2025-W01:2026-W16` were used. The output contains 561 unique predictor pairs
and 68 component-specific association rows. Absolute correlation thresholds
were fixed at 0.70 and 0.90. The reference matrix yielded 19 dependence-warning
pairs at or above 0.70 and 11 high-dependence pairs at or above 0.90.

Standardized associations use Q75–Q25 contrasts for continuous predictors,
fixed 0→1 contrasts for binary/imputation indicators, and explicit calendar
labels. Occurrence contrasts include the linear predictor contrast and odds
multiplier. Positive-count contrasts retain mean-parameter-ratio terminology.
No global raw-coefficient ranking is used.

The canonical P4 output root did not retain a
`bootstrap_coefficient_stability.csv` artifact. No new coefficient bootstrap or
refitting was performed; coefficient intervals/stability are therefore not
claimed by P7G.

## 6. Analysis D — Calibration by support class and horizon

Support classes were joined from the canonical P4 archive without changing P4
thresholds. P2 calibration definitions and fixed equal-width probability bins
were reused. The point metrics and reliability rows are in:

* `results/support_horizon_calibration_metrics.csv`;
* `results/support_horizon_reliability.csv`.

Deterministic target-week block bootstrap intervals use 199 resamples per
support class and horizon with the P2 seed family recorded in
`results/support_horizon_bootstrap_ci.csv`. No independent row bootstrap or
model refitting was used. Support-stratified metrics remain descriptive, with
the `EXTRAPOLATIVE` class retaining the highest Brier score across the evaluated
horizons in the canonical output.

## 7. Provenance and reproducibility

`results/source_hash_manifest.json` records the canonical P2/P4 sources, frozen
model/scaling artifacts, feature cache, node table, and queen graph. The
source registry is `results/source_registry.csv`. The compact result tables
were produced under isolated Atlas output root
`/project/disease_ecology/STGNN-output/p7g_manuscript_evidence_20261030_r2/`;
the complete source archive was not copied locally.

The focused validator is
`scripts/validate_p7g_outputs.py`. It checks required files, frozen hashes,
source rows, predictor-pair counts, support/horizon coverage, reliability-bin
counts, bootstrap count, and the no-model-fitting contract.

Technical diagnostic figures generated from the compact results are under
`figures/`, with captions in `figures/p7g_figures_captions.md`. These figures
are evidence-review displays, not manuscript prose. Rebuilding the figures
produced identical PNG hashes and identical source-derived plotted values. Base
R PDF device metadata differed between renders; this benign rendering
difference is recorded rather than treated as a scientific discrepancy.

## 8. Remaining limitations

* P4 coefficient-bootstrap stability was not retained in the canonical output
  root; no replacement refit was authorized.
* First-recorded detection strata and support-class results are descriptive and
  may be sparse for selective ranks or individual classes.
* Residual dependence does not remove the previously documented spatial,
  frontier, regional, or count-process limitations.
* The P2 evaluation archive is retrospective realized-environment evaluation;
  P7G does not establish new prospective environmental availability.
* Association summaries are conditional predictive associations, not causal
  effects or universal predictor importance.

## 9. P7G decision

The required bounded diagnostics, provenance, fail-closed validation, and
Atlas execution completed with explicit limitations. No frozen scientific
artifact was modified.

P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS
