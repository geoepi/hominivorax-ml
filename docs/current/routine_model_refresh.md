# Proposed routine model-refresh policy

**Status: proposal only.** This document separates routine data refresh from
scientific performance monitoring for discussion. It does not supersede the
current P0–P7 plan, P6 production runbook, production acceptance rules, or any
branch-protection/release requirements. Until this proposal is separately
approved, the existing rules remain binding. It does not authorize W44
promotion or another model fit.

## Routine data refresh

**Purpose:** update the established `STRUCTURED_A3` model with the latest
accepted observations and available environmental predictors while preserving
the scientific specification. A refresh that changes the training vintage or
coefficients creates a versioned candidate; it never edits the original W16
freeze or replaces production automatically.

The proposed refresh record would include:

- input identity, schema, checksum, duplicate and revision audits, accepted
  complete-week cutoff, and predictor availability;
- exact preservation of the 34-predictor order, transforms, response,
  resolution/domain, theta, penalty, objective, and history cutoffs;
- optimizer convergence and finite parameter/prediction checks;
- prediction, raster, and artifact-manifest integrity;
- reproducible source/software identity and stable checksums;
- explicit production/development/retrospective output roots, fail-closed
  overwrite protection, and production-isolation verification;
- basic comparison safeguards against a declared reference, reported as
  diagnostics rather than automatic promotion criteria.

## Scientific performance monitoring

Monitoring assesses predictive reliability over time without delaying each
routine data update. It would register issue-time forecasts before outcomes,
track outcome maturity and reporting completeness, and evaluate mature targets
against prespecified baselines. The record should include calibration and
accuracy, horizon, region and frontier diagnostics, spatial residual
correlation, uncertainty and extrapolation, support changes, and triggers for
deeper scientific review.

Monitoring results do not refit, recalibrate, alter thresholds, or promote a
candidate. A trigger opens a separately governed scientific review. Forecasts
whose targets are immature or whose issue-time inputs cannot be demonstrated
remain ineligible for confirmatory scoring.

## Relationship to current qualification rules

The existing `docs/production_qualification_plan.md` requires its P0–P7
qualification process for production designation. This proposal would allow a
routine data refresh to use a proportionate set of input, specification,
optimization, artifact, isolation, and basic performance safeguards, while
reserving the full scientific monitoring program for prespecified periodic
evaluation or a triggered review. That change requires explicit policy
approval and a reconciliation of production-acceptance language before use.

Until then, do not describe a routine refresh as qualified solely because it
passed operational checks. The W44 model remains
`CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`; its Q1 retrospective
results have `scientific_qualification_decision: NOT_ASSIGNED` because target
maturity is uncertified.
