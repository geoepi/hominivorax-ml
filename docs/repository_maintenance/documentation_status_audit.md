# Documentation and status audit

## Status conflicts found

The mainline documentation still identified the W29 fit as the latest
descriptive full fit, observations through W31, and complete A3 support only
through W29. Those statements were valid for the October documentation
snapshot but had become ambiguous after the W44 candidate refresh and Q1
retrospective. Other docs described `production_fullfit` as the production
workflow without clearly separating it from the P6 inference implementation.
The tracked production example uses a W29 observation filename and includes a
developer-specific R library path, so it cannot be treated as current deployed
configuration.

## Corrections

- Added [docs/current/status.md](../current/status.md) as the canonical table
  for the original W16 freeze, the W29 active artifact, the W44 candidate, Q1
  retrospective results, and pending independent fixed-W44 evaluation.
- Updated `README.md`, `MODEL_STATUS.md`, and current model/validation/data/
  artifact/limitation/output pages to point to that canonical status and retain
  historical dates without describing W29 as the newest candidate.
- Clarified that W16 P1–P7 outcomes do not transfer to W44 and that Q1
  retrospective metrics are descriptive with decision `NOT_ASSIGNED`.
- Updated the Atlas guide, production runbook, and entrypoint inventory to
  distinguish P6 issue-time inference, the P0–P5 full-fit/no-refit scoring
  pipeline, and the W44 development candidate refresh.
- Added the decision register for exact A3–A6 and point-proximity codes.
  Residual spatial correlation remains a limitation/diagnostic, not an
  elimination requirement.
- Marked October release audits as historical snapshots and added a
  non-destructive W44 branch-reconciliation addendum.
- Added a non-binding routine-refresh proposal; existing P0–P7 and production
  acceptance rules remain in force until explicit policy approval.
