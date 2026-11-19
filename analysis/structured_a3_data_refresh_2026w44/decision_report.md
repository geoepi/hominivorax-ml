# Final execution report

## I. Governance

Reviewed the user instructions, repository guidance, execution governance, Atlas SSH policy, and the approved production qualification plan. Canonical repository: geoepi/hominivorax-ml. Atlas was accessed only through Windows, WSL Ubuntu, and the repository-approved /home/johnh/bin/atlas-ssh wrapper. Restricted data and fitted outputs were not copied into the repository.

## II. Canonical starting state

GitHub main started at 6715a4397dad21a77414bd2ce41586751290f374. Work occurred on the isolated branch analysis/structured-a3-2026w44-refresh in D:/Github/STGNN/worktrees/structured-a3-2026w44-refresh. The user's existing dirty checkout was preserved.

Atlas upstream STGNN was at 87b9d32cf0dbdafbc91d2017a0d816fdf76bdb3a. The deployed production code checkout was at b1095e7fc8ef94ce4613aa7adcdc643e76a2e927.

## III. Observation data audit

The November 13 source is 7,304,653 bytes, SHA-256 8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc, modified November 18. Its schema is date, host, lon, lat; it has 167,078 rows, no blank fields, no invalid dates, and globally valid coordinates for all rows. It spans 2022-02-10 through 2026-11-13, with observed rows in W44, W45, and W46.

The release does not document the latest complete week. The filename date is not a completeness declaration. The follow-up duplicate/precision investigation confirms 2,311 duplicated `(date, lon, lat)` key groups in the updated source (4,622 participating rows; 2,311 redundant rows), including 988 groups in the frozen fit horizon (1,976 participating; 988 redundant). The earlier 2,295 and 980 figures are confirmed as repeated complete-row groups/redundant rows, not all coordinate-key groups. Exact source-coordinate duplication is therefore confirmed. Whether repeated records represent separate detections or duplicate ingestion remains undocumented.

## IV. Environmental data audit

All 12 frozen dynamic predictor products have 252 contiguous weekly files from 2022-W01 through 2026-W44. W44 sidecars cover October 26 through November 1, use weekly-v3-support-mask, and match raster checksums. W29 and W44 processing-spec and template hashes agree.

After correcting the stored node row/column index origin, no W44 predictor has missing values at any of the 10,037 A3 nodes. Across the original 68-week fit horizon, all 8,190,192 dynamic values exactly match the frozen bundle. Provider release-time or revision-lag metadata remains unavailable. Atlas Python reported missing proj.db; the grid and projection parameters align, but authority normalization remains a limitation.

## V. Frozen specification verification

The frozen model is STRUCTURED_A3: 25 by 25 km canonical cells, 10,037 nodes, 34 ordered predictors, a penalized spatiotemporal hurdle model, Bernoulli/logistic occurrence, zero-truncated negative-binomial positive counts, and response threshold count greater than zero. The original frozen fit uses 2025-W01 through 2026-W16, theta 0.7018903965556372, penalty 0.01, and exact_joint_hurdle_nll. Flight-path and SIT predictors are excluded. Fit is deterministic given inputs; the recorded diagnostic permutation seed is 20261006.

## VI. Candidate data vintage

No candidate vintage was assigned. The environmental endpoint is W44, but the observation complete-week endpoint is unknown; W46 is only the latest observed week. The proposed label STRUCTURED_A3_2026W44 was not used because the verified endpoint is unknown.

## VII. Atlas execution status

Read-only audit only. No model refresh, fit, Slurm submission, or candidate artifact creation occurred. No job IDs or execution logs exist. Storage quota was not checked because no large output was created.

## VIII. Qualification results

Stage A input and compatibility audit is complete and blocked. Stage B frozen specification audit is complete. Stages C and D were not run under the attached stop gate. No qualification criteria are reported as passed for a new candidate.

## IX. Artifact inventory and integrity

The public frozen model SHA-256 is 8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e. The frozen evaluation manifest SHA-256 is 9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61.

The pre-existing Atlas fullfit model SHA-256 is 1cb694f4323ac2d05d973b5631539bd4e3a95ed3ffe3a7405a9e35c6b377092e; its fit manifest records 2025-W01 through 2026-W29 and fit_complete. No new model artifacts were produced.

## X. Production-isolation verification

The active Atlas configuration still points to the pre-existing production inputs and output. The separate proposed refresh output path did not exist at audit time. No Atlas write, configuration change, production pointer change, or promotion occurred.

## XI. Repository and pull-request status

The original refresh audit consisted of audit documentation and machine-readable manifests (classification A). The follow-up adds read-only audit scripts, aggregate outputs, documentation, and focused synthetic tests (classification C; no production data pathway or model code changed). Its targeted tests and cross-check are documented in observation_duplicate_precision_audit.md. No package-wide or HPC validation was run. Draft pull request 31 remains open with the refresh result and blocker.

## XII. Outstanding limitations and blockers

1. The new observation release has no documented latest complete week.
2. Most original-fit-horizon observation key multiplicities differ from the frozen source; the size and cause of the historical revisions are undocumented.
3. Exact duplicate observation coordinate keys are present at source precision; the source does not document whether repeated rows represent separate detections or duplicate ingestion. See observation_duplicate_precision_audit.md for the superseding counts and method reconciliation.
4. The frozen source filename ends in 2027-07-31, while its content ends in 2026-07-31.
5. Provider release-time or revision-lag metadata for the environmental sources was not established.
6. Atlas's configured rasterio environment cannot locate proj.db, limiting authority-code validation.

## XIII. Final decision

REFRESH_BLOCKED_BY_INPUT_DATA.

The duplicate-specific classification is OBSERVATION_DUPLICATES_CONFIRMED_AT_SOURCE. The overall refresh decision remains REFRESH_BLOCKED_BY_INPUT_DATA. Resume candidate work only after the source owner documents the complete observation week, explains the historical revision process, and clarifies duplicate-record semantics. Re-audit the resulting immutable source snapshot before any candidate model execution. No decision to modify the model, change the data contract, or promote a production artifact was made.

## Follow-up addendum — observation duplicate and precision audit

The follow-up is classified C because it adds executable read-only audit logic and focused synthetic tests. The audit scripts do not change the observation source, production data path, model code, dependencies, or scientific parameters. Validation used the intended Atlas R environment wrapper for an independent base R checksum/key-count cross-check and the Atlas project Python environment for the focused 12-test synthetic module. The Python environment did not contain pytest; the available standard-library unittest runner passed all 12 tests, and no dependency or environment was installed or changed. The audit did not run the package suite, HPC workflows, model fitting, Slurm, or production qualification because those are outside this integrity investigation.

The source hashes matched before parsing. Python and R agreed on the raw-record, raw-key, and exact-decimal key aggregates. The detailed metrics, rounding sensitivity, method recovery limitations, and source-integrity classification are in observation_duplicate_precision_audit.md and its aggregate outputs. The original findings above remain in the report for traceability; the duplicate-specific statements are superseded by the follow-up findings.
