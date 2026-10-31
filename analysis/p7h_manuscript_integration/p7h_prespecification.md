# P7H Manuscript Evidence Integration Prespecification

## Purpose and boundary

P7H integrates the canonical P7G manuscript-evidence outputs into the
publication package. It is a publication-integration task, not a model,
prediction, calibration, sensitivity, or support-threshold task. The frozen
`STRUCTURED_A3` artifact, P0--P7 decisions, P5A `E0_LAST_AVAILABLE` contract,
and P6 production configuration are immutable inputs.

No fitting, refitting, tuning, recalibration, feature selection, new
importance method, or scientific redefinition is permitted. All manuscript
values must trace to a tracked machine-readable source artifact and all
interpretations must preserve the source artifact's scope.

## Canonical source hierarchy

1. P0 freeze manifest and frozen model artifact for model identity and schema.
2. P1--P6 canonical machine-readable results for qualified performance,
   support, proxy, and production claims.
3. P7 publication artifacts for existing tables, figures, wording, and
   provenance structure.
4. P7G machine-readable outputs for residual dependence, first-recorded
   detection ranking, predictor dependence/standardized associations, and
   support-stratified calibration.

P7G values will be copied or referenced only after source hash and schema
validation. Missing P4 coefficient-bootstrap artifacts will remain missing;
no intervals will be fabricated.

## Evidence integration rules

- Add only numerical evidence present in the P7G result files.
- Use the exact P7G analysis populations, horizons, thresholds, graph
  definitions, and bootstrap design; do not reinterpret them as new validation
  regimes.
- Describe spatial/temporal dependence as a residual diagnostic, not as proof
  of model failure or as a refitted spatial holdout.
- Describe first-recorded detection ranking as event-capture evidence within
  the prespecified frontier-relative and full-domain pools; do not claim
  superiority over non-informative reference scores.
- Describe standardized associations as conditional predictive associations,
  not causal effects or universal feature importance. Report dependence among
  predictors and the absence of retained coefficient-bootstrap intervals.
- Describe support-stratified results as empirical performance conditional on
  unchanged support classes; support is not a direct correctness probability.
- Preserve retrospective P2 wording, E0 proxy dependence, sparse frontier and
  regional/U.S. support, count-process bias, observation-process limitations,
  residual dependence, lack of a refitted spatial holdout, and missing P4
  coefficient-bootstrap stability as explicit limitations.

## Publication package decisions

The existing P7F main figures remain unchanged except that Figure 6 may be
replaced if the P7G standardized-association table supports a clearer,
non-misleading display. A replacement must retain Figure 6 numbering, archive
the superseded P7F asset without deletion, identify scale classes, and avoid a
global absolute-coefficient ranking. P7G diagnostic figures and tables will be
added to the supplement only when they close a manuscript-evidence gap without
duplicating the main package.

The claim registry, results synthesis, Methods, Results, Limitations,
Discussion outline, and reviewer checklist will be updated in place only with
source-traceable statements. The publication source registry and
reproducibility manifest will be refreshed after all edits.

## Precision and presentation

Machine-readable artifacts retain full source precision and SHA-256 hashes.
Human-readable prose uses four decimal places for probabilities/metrics where
appropriate, one decimal place for percentages, and integers for counts. Any
rounding is presentation-only and will be checked against the unrounded source
value. Confidence intervals are reported only when present in canonical P7G
bootstrap artifacts.

## Required validation

P7H must verify: the frozen model hash; P7G source hashes and decision;
publication source schemas; claim-to-source traceability; no model-fitting
invocation; complete limitation coverage; deterministic publication rebuilds;
and clean output hashes apart from explicitly permitted generation timestamps.
The final decision is `P7H_MANUSCRIPT_PACKAGE_READY` only if all required
evidence is complete and reproducible. Otherwise the package is
`P7H_MANUSCRIPT_PACKAGE_READY_WITH_LIMITATIONS` when limitations are explicit
and do not invalidate the integrated evidence, or `P7H_MANUSCRIPT_PACKAGE_NOT_READY`
when primary claims cannot be traced or reproduced.

## Acceptance criteria

- P0 and the frozen artifact remain unchanged.
- P7G source hashes and numerical values are unchanged.
- Every newly integrated claim has a machine-readable source and bounded
  interpretation.
- Required Methods/Results/Limitations/Discussion/checklist artifacts exist.
- P7F main figures remain unchanged except for a documented Figure 6
  replacement, if justified.
- Supplementary additions are minimal and source-registered.
- Publication generation is deterministic and safe on missing/mismatched
  source artifacts.
- Residual dependence, observation-process, regional/U.S., count, support,
  E0, spatial-holdout, retrospective-evaluation, and missing-uncertainty
  limitations remain visible.
