# P1 Production Validation Report

## I Governance

This report follows the production freeze and P1 qualification boundary. The analysis is evaluation-only: no refit, recalibration, threshold tuning, feature selection, neural/graph fitting, or P0 modification was performed.

## II P0 Canonicalization

P0 was merged to `main` before this branch was created. The frozen model is `STRUCTURED_A3` and the artifact is verified by the shared production-freeze verifier.

## III P1 Repo State

Repository SHA at execution: `690b6c98caa8461aeea683eb0cf6563ef22c730e`. Results are written under `analysis/p1_production_validation/` and exclude protected raw data.

## IV Frozen Model Verification

Verifier status: `{'manifest': 'PASS', 'artifacts': 'PASS', 'predictor_schema': 'PASS', 'model_metadata': 'PASS', 'known_answer_inference': 'PASS', 'deterministic_inference': 'PASS', 'trains_model': False}`. Model ID: `STRUCTURED_A3`; predictors: `34`; fit horizon: `2025-W01` through `2026-W16`; theta: `0.7018903965556372`; penalty: `0.01`.

## V Existing Validation Audit

Existing historical W17–W29 results and the prior W30–W39 `STRUCTURED_A3_FULLFIT` archive were audited. The prior full-fit archive was not promoted as P1 evidence because its model ID and coefficients differ from the exact P0 compact artifact. P1 evidence below is rescored with exact `STRUCTURED_A3`.

## VI Temporal

The complete post-fit interval evaluated was `2026-W30, 2026-W31, 2026-W32, 2026-W33, 2026-W34, 2026-W35, 2026-W36, 2026-W37, 2026-W38, 2026-W39`. Primary joint hurdle NLL: `0.17256384770343097`.

## VII Spatial

Spatial transfer uses the predeclared country/domain regions in the canonical node table, with 5x5 raster-block uncertainty rather than random row splits. Sparse U.S. outcome support is retained as a limitation.

## VIII Spatiotemporal

Spatiotemporal transfer is evaluated on the later W30–W39 interval within the same geographic regions, using exact week/node joins and joint week-block-by-spatial-block uncertainty.

## IX Frontier

Frontier classes distinguish established/core detections, previously occupied cells, previously unoccupied cells, and newly detected/frontier positives using only causal prior-history features.

## X Artifacts

Machine-readable metrics, bootstrap intervals, frontier summaries, decision rules, input hashes, and bounded figures are stored alongside this report.

## XI Atlas

Execution used the repository-authorized Atlas Python environment and validated refresh through `2026-W39`. Protected inputs were not copied into Git. The exact-frozen scoring job was Slurm `21059059` (completed, exit 0); figure rendering was Slurm `21059083` (completed, exit 0).

## XII CI/PR/Merge

P1 changes require the normal branch push, pull request, hosted-check review, merge, and post-merge main validation recorded in the task handoff.

## XIII P1 Decision

Decision: `SUPPORTED_WITH_LIMITATIONS`. Temporal: `SUPPORTED`; spatial: `SUPPORTED_WITH_LIMITATIONS`; spatiotemporal: `SUPPORTED_WITH_LIMITATIONS`; frontier: `SUPPORTED_WITH_LIMITATIONS`.

The limitation is substantive: later transfer is informative for discrimination and ranking, while sparse regional/frontier support and count-process bias prevent an unrestricted production-validity claim.

P1_TRANSFER_VALIDATION_SUPPORTED_WITH_LIMITATIONS
