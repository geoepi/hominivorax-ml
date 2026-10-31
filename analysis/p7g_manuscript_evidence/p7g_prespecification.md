# P7G Manuscript Evidence Completion — Prespecification

## Status and scope

This document is the locked analysis contract for P7G. It is committed before
any result-bearing P7G execution. P7G is an evaluation and evidence-completion
phase only. It does not modify the frozen `STRUCTURED_A3` model, its fitted
coefficients, predictor schema, penalty, theta, support thresholds, P0–P7F
artifacts, or production configuration.

No model fitting, refitting, recalibration, feature selection, ablation,
SHAP/PDP/ALE analysis, new spatial cross-validation, or causal analysis is
permitted. All computations below are descriptive or evaluation-only and must
fail closed when the canonical source artifacts or required provenance are not
available.

## Canonical sources and integrity

The primary prediction source is the canonical P2 rolling-origin archive:

* `analysis/p2_operational_nowcast/results/prediction_archive_manifest.json`
* Atlas archive:
  `/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/predictions/rolling_origin_predictions.parquet`
* expected SHA-256: `918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170`
* expected rows: `632331`

The canonical P4 support source is:

* Atlas file:
  `/project/disease_ecology/STGNN-output/p4_uncertainty_extrapolation_20261029/support_classifications.parquet`
* expected SHA-256: `c35bf794fcc882e3ea71bc1a279b90e4f32aeff412a9399f2fb25e383141d058`
* expected rows: `632331`

The P4 novelty/support metadata and the P2 archive manifest are the provenance
sources for support thresholds, reference weeks, and the exact frozen
34-predictor ordering. The frozen model remains `STRUCTURED_A3` with expected
SHA-256 `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.
The P4 training reference is `2025-W01` through `2026-W16`.

Existing P4 coefficient-bootstrap artifacts, if present and integrity-verified,
will be reused for coefficient uncertainty/stability summaries. P7G will not
create a new coefficient refit or alter the P4 bootstrap design.

## Evaluation records and horizons

Eligible P2 rolling origins are the canonical weekly origins `W16` through
`W36` for which the P2 archive contains the required horizon records. Analyses
use horizons `h=1`, `h=2`, and `h=3`, retaining target weeks exactly as recorded
in the archive. Origin, target, node, and horizon keys must be unique before
aggregation. Rows are paired only on identical keys and target weeks.

No intervening future week may be used to construct a predictor, residual,
rank, or support value for an earlier issue origin. The P2 archive remains the
unchanged retrospective realized-environment reference.

## A — Spatial and temporal dependence

### Residual definitions

The canonical P2/P3/A3 diagnostic definitions are reused exactly:

* occurrence residual: `observed_positive - p_occurrence`;
* conditional positive-count residual: `observed_count - conditional_count_mean`,
  evaluated only where `observed_count > 0`;
* full hurdle residual: `observed_count - expected_count`.

Raw occurrence is `observed_positive`; raw positive-count values are
`observed_count` on the same positive-count mask. No alternative residual
definition, variance stabilization, or reweighting is introduced.

The spatial graph is the canonical queen graph already used by the prospective
diagnostic implementation, with its `source_node` and `target_node` edge
convention. Spatial association uses the existing Moran-I implementation and
finite-value handling, including its node-count normalization and centered
cross-product convention. It is descriptive association, not a new spatial
validation design.

Spatial summaries use graph-distance shells 1, 2, 3, and 4. Shells are shortest
path distance exactly equal to the shell order; self-pairs and lower-order
shells are excluded. If a shell has no estimable pair set, its status is
`NOT_ESTIMABLE` rather than being silently substituted.

For temporal dependence, lag `ell=1,2,3` pairs are matched within the same
canonical cell and horizon using target weeks separated by exactly `ell` ISO
weeks. No mixed-horizon or mixed-origin pairing is allowed. Pooled and, where
estimable, cell-level summaries are reported for raw and residual quantities
using the canonical finite-value masks.

## B — First-recorded detection and early-warning ranking

First-recorded detection is defined from the P2 history fields: a target-week
positive with `previously_occupied == false`, with no earlier eligible positive
for that cell in the available leakage-safe P2 sequence. The first event per
cell is retained. Contradictory or missing history fields cause explicit event
exclusion.

For each event, rankings are formed separately for its exact origin, target week,
and horizon. Two rank pools are prespecified:

1. `FULL_DOMAIN`: all eligible cells in that origin/horizon record;
2. `FRONTIER_RELATIVE`: cells with `previously_occupied == false` in that same
   origin/horizon record.

The primary score is `p_occurrence`. Existing simple reference scores
`historical_prevalence_probability` and `persistence_probability` are retained
only when present and informative; no new ranking model is fitted.

Ranks use ascending score, with higher score meaning higher risk, and average
ranks for ties. The fixed midrank percentile is:

`risk_percentile = 100 * (midrank - 0.5) / n`.

Top-k capture is evaluated at `k = 0.01, 0.05, 0.10, 0.20` of each pool using
the corresponding percentile cutoff. Event coverage, event count, capture
count/proportion, and sparse-stratum warnings are reported. No cutoff is tuned
after results are observed.

The h=3 to h=1 trajectory is summarized only for first-detection events with
all required horizon records, using the same event set and rank definitions
across horizons.

## C — Predictor dependence and standardized associations

The exact frozen 34-predictor ordering and existing P4 training reference are
required. Predictor dependence uses Pearson and Spearman pairwise association
on the exact reference matrix when available. Fixed thresholds are absolute
correlation `0.70` for a dependence warning and `0.90` for a high-dependence
warning. Missing or non-estimable pairs are recorded, not imputed.

Standardized contrasts use the actual fitted scale and existing P4/frozen
scaling state:

* continuous predictors: Q75 minus Q25 from the exact training reference;
* binary predictors: 0 to 1;
* calendar predictors: labeled as calendar contrasts, not ordinary continuous
  effects;
* imputation indicators: labeled separately from source measurements;
* identity/unstandardized terms: labeled explicitly and not ranked against
  standardized terms.

For occurrence, report `beta * delta` on the linear predictor scale and
`exp(beta * delta)` as the corresponding odds multiplier. For positive counts,
preserve the exact fitted mean parameterization and report a mean-parameter
ratio for the same contrast; it is not an odds ratio or causal effect.

Existing P4 coefficient-bootstrap artifacts are reused for intervals or
stability summaries where their schema and provenance match the frozen feature
ordering. No new bootstrap refitting is performed. Predictors are not globally
ranked by raw coefficient magnitude when scaling classes differ.

All association language is conditional predictive association, not causal
effect, feature importance, or proof of ecological mechanism.

## D — Calibration by support class and horizon

Support classes are unchanged: `SUPPORTED`, `CAUTION`, and `EXTRAPOLATIVE`.
Support is joined to P2 records only on the exact canonical prediction key. P4
thresholds and class definitions are never recalculated.

Within each horizon and support class, use the exact P2 calibration
implementation and binning convention, including finite-value rules. Primary
summaries are N, positives, prevalence, Brier, calibration intercept, slope,
log loss, AUROC, and AUPRC where estimable. ECE is not introduced.

Uncertainty intervals for key support-stratified metrics use target-week block
resampling with the P2 bootstrap convention and seed metadata where feasible.
Rows from a target week are resampled together. Independent row bootstrap is
prohibited. Sparse strata receive `NOT_ESTIMABLE` or an explicit warning.

## Data validity, estimability, and fail-closed rules

Before analysis, verify expected source hashes, schemas, row counts, key
uniqueness, horizon/origin coverage, and support join cardinality. A failed
integrity check blocks result generation. Future-dated or mismatched records,
duplicate keys, missing predictor metadata, and unresolved source versions are
blocking errors for the affected analysis.

Every analysis records its denominator, exclusions, missingness, and
estimability status. A metric is `NOT_ESTIMABLE` when its required finite sample
or outcome variation is absent. No fallback, manual value, alternative source,
or post hoc subset is permitted to create a passing result.

## Required outputs and provenance

Write compact, machine-readable outputs under
`analysis/p7g_manuscript_evidence/results/`, figures under `figures/`, and
technical documentation under this phase directory. Required outputs include
source validation, spatial/temporal dependence summaries, early-warning/ranking
summaries, predictor dependence and standardized association summaries,
support-by-horizon calibration metrics, uncertainty/coverage records, a source
hash manifest, and a decision record. Detailed Atlas row archives are not copied
to the repository; only compact derived summaries and provenance are retained.

Each result table includes source artifact identifiers, hashes where applicable,
analysis version, and deterministic configuration values. Atlas execution uses
the authorized WSL/Ubuntu route and an isolated P7G output root.

## Interpretation and decision rules

P7G closes evidence gaps only when canonical source data are sufficient and the
prespecified estimands are estimable. Results may document persistent
limitations; they may not upgrade a scientific claim, erase sparse support, or
turn association into causation.

The final decision is one of:

* `P7G_MANUSCRIPT_EVIDENCE_COMPLETE` — all four bounded analyses and required
  provenance/validation artifacts are complete and reproducible;
* `P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS` — the evidence package
  is reproducible but one or more analyses remain sparse, partially estimable,
  or tooling-limited;
* `P7G_MANUSCRIPT_EVIDENCE_NOT_COMPLETE` — a required source or validation
  contract failed, or a primary analysis cannot be performed without
  unauthorized new science.

