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

## VI. Candidate data vintage at the initial audit (historical)

No candidate vintage was assigned. The environmental endpoint is W44, but the observation complete-week endpoint is unknown; W46 is only the latest observed week. The proposed label STRUCTURED_A3_2026W44 was not used because the verified endpoint is unknown.

## VII. Atlas execution status at the initial audit (historical)

Read-only audit only. No model refresh, fit, Slurm submission, or candidate artifact creation occurred. No job IDs or execution logs exist. Storage quota was not checked because no large output was created.

## VIII. Qualification results at the initial audit (historical)

Stage A input and compatibility audit is complete and blocked. Stage B frozen specification audit is complete. Stages C and D were not run under the attached stop gate. No qualification criteria are reported as passed for a new candidate.

## IX. Artifact inventory and integrity

The public frozen model SHA-256 is 8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e. The frozen evaluation manifest SHA-256 is 9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61.

The pre-existing Atlas fullfit model SHA-256 is 1cb694f4323ac2d05d973b5631539bd4e3a95ed3ffe3a7405a9e35c6b377092e; its fit manifest records 2025-W01 through 2026-W29 and fit_complete. No new model artifacts were produced.

## X. Production-isolation verification before candidate execution (historical)

The active Atlas configuration still points to the pre-existing production inputs and output. The separate proposed refresh output path did not exist at audit time. No Atlas write, configuration change, production pointer change, or promotion occurred.

## XI. Repository and pull-request status at the initial audit (historical)

The original refresh audit consisted of audit documentation and machine-readable manifests (classification A). The follow-up adds read-only audit scripts, aggregate outputs, documentation, and focused synthetic tests (classification C; no production data pathway or model code changed). Its targeted tests and cross-check are documented in observation_duplicate_precision_audit.md. No package-wide or HPC validation was run. Draft pull request 31 remains open with the refresh result and blocker.

## XII. Outstanding limitations and blockers at the initial audit (historical)

1. The new observation release has no documented latest complete week.
2. Most original-fit-horizon observation key multiplicities differ from the frozen source; the size and cause of the historical revisions are undocumented.
3. Exact duplicate observation coordinate keys are present at source precision; the source does not document whether repeated rows represent separate detections or duplicate ingestion. See observation_duplicate_precision_audit.md for the superseding counts and method reconciliation.
4. The frozen source filename ends in 2027-07-31, while its content ends in 2026-07-31.
5. Provider release-time or revision-lag metadata for the environmental sources was not established.
6. Atlas's configured rasterio environment cannot locate proj.db, limiting authority-code validation.

## XIII. Initial decision (historical; superseded for the controlled refresh)

REFRESH_BLOCKED_BY_INPUT_DATA.

The duplicate-specific classification is OBSERVATION_DUPLICATES_CONFIRMED_AT_SOURCE. The overall refresh decision remains REFRESH_BLOCKED_BY_INPUT_DATA. Resume candidate work only after the source owner documents the complete observation week, explains the historical revision process, and clarifies duplicate-record semantics. Re-audit the resulting immutable source snapshot before any candidate model execution. No decision to modify the model, change the data contract, or promote a production artifact was made.

## Follow-up addendum — observation duplicate and precision audit

The follow-up is classified C because it adds executable read-only audit logic and focused synthetic tests. The audit scripts do not change the observation source, production data path, model code, dependencies, or scientific parameters. Validation used the intended Atlas R environment wrapper for an independent base R checksum/key-count cross-check and the Atlas project Python environment for the focused 12-test synthetic module. The Python environment did not contain pytest; the available standard-library unittest runner passed all 12 tests, and no dependency or environment was installed or changed. The audit did not run the package suite, HPC workflows, model fitting, Slurm, or production qualification because those are outside this integrity investigation.

The source hashes matched before parsing. Python and R agreed on the raw-record, raw-key, and exact-decimal key aggregates. The detailed metrics, rounding sensitivity, method recovery limitations, and source-integrity classification are in observation_duplicate_precision_audit.md and its aggregate outputs. The original findings above remain in the report for traceability; the duplicate-specific statements are superseded by the follow-up findings.

## Corrected-source re-audit addendum — 2026-11-19

The duplicate-specific decision above applies to the prior source snapshot, SHA-256 `8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc`, and is retained as historical evidence. Re-audit of the corrected file at the same source path (SHA-256 `2f9cf04ffe01712b8e5498d809f542d159ff1cb33ae8b567aa6644e9c4f05de5`) found 2,263 duplicate exact-decimal `(date, lon, lat)` groups overall and 975 in the original W16 horizon. The source decision is therefore `OBSERVATION_DUPLICATES_REMAIN`; current-source uniqueness is not established. Because the prior immutable source was unavailable, it is not possible to determine whether all 2,311 previously reported groups were resolved or which individual keys persisted. No new schema, missingness, date-validity, or coordinate-validity issue was found. Overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA` because duplicate keys remain, W44 completeness is undocumented, historical revision provenance is unresolved, and the W29 artifact-lineage question remains separate. The corrected-source re-audit and its aggregate outputs are documented in `observation_corrected_source_reaudit.md`.

## Minimal observation source verification — 2026-11-19

The current file at the authoritative path has SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`, size 7,191,829 bytes, and modification time 2026-11-19 10:06:23.592700507 -0600. The checksum matched before and after a 3.46-second Rscript verification using Atlas module `r/4.5` (R 4.5.1).

The opened file has 164,767 rows and four columns. Its actual column order is `date, lon, lat, host`; the expected four names are present, but the order differs from the earlier manifest. Using the named `(date, lon, lat)` fields, R found 164,767 unique keys and zero redundant keys. Missing values, invalid dates, and invalid coordinates were all zero. Dates range from 2022-02-10 to 2026-11-13. The original W16 horizon has 91,005 rows and the extended W44 horizon has 118,892 rows. Weekly observations for W42–W46 are 994, 1,021, 911, 668, and 300, respectively.

**Current observation-source decision: `OBSERVATION_SOURCE_CORRECTION_VERIFIED`.** This result applies to SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`; prior duplicate findings remain historical for their recorded checksums. The duplicate-related blocker is closed. Overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA` because W44 reporting completeness, historical revision provenance, and the separate W29 artifact-lineage question remain unresolved.

## Controlled refresh resumption — 2026-11-19

The user explicitly accepted the corrected observation snapshot as the authoritative replacement, selected 2026-W44 as a provisional endpoint, accepted undocumented reporting completeness and historical revisions as limitations, and deferred the separate W29 artifact-lineage investigation. This resolves the readiness decision for the controlled refresh without asserting that W44 is complete or that historical revisions are explained.

The current source checksum was rechecked on Atlas before refresh: `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`. The established `scripts/run_task2e_refresh.R` ingestion uses named fields (`date`, `lon`, `lat`, `host`) through `data.table::fread`, so the verified schema order `date, lon, lat, host` is compatible. The current shared Task 2A response bundle ends at W29, while the accepted environmental raster inventory reaches W44; the approved Task 2A builder therefore needs to construct the W44 bundle in the separate candidate root. The existing Task 1 preflight, revised-domain graph, static A3, and runtime inputs are present at their established Atlas paths. The exact candidate output path `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44` was absent before execution.

**Input-readiness decision: `REFRESH_INPUT_READINESS_ESTABLISHED`.** This decision accepts the stated limitations for this controlled refresh; it does not certify reporting completeness or establish revision provenance. Stage C and Stage D execution status is recorded in the subsequent resumption addendum.

## Controlled W44 candidate execution — 2026-11-19

The authorized work remained on `analysis/structured-a3-2026w44-refresh` at repository commit `44d44197a0f55b828f4f386afc02a3770e38ac33`, in the isolated local and Atlas worktrees. Atlas was accessed only through the approved WSL/Ubuntu SSH wrapper. Candidate observations and fitted outputs remained on Atlas. The change classification is D because this work exercised the controlled data and model pathway; no model algorithm, predictor definition, or production configuration was changed.

### Candidate data refresh

Task 2A job `21272742` failed before producing candidate files because the first R library path lacked `data.table`. The retry, `21272766`, completed after using the already-installed combined project and user R libraries; no packages or shared software environments were changed. The candidate feature bundle has 16,756 canonical nodes, 148 target weeks from 2024-01-01 through the week beginning 2026-10-26, 12 dynamic features, and 10 static features.

Task 2E job `21272811` completed at `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/revised_model_data`. It used source SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`, 164,767 rows, and 164,767 valid dates and coordinates. Its source diagnostics report zero exact repeated complete rows and zero duplicate `(date, lon, lat)` keys. The response spans 2025-W01 through the user-selected provisional endpoint 2026-W44 (96 weeks), with 10,037 nodes and 34 frozen predictors. These aggregate diagnostics agree with the minimal source verification. The release itself still does not certify W44 completeness.

### Full-fit and candidate artifact checks

Full-fit job `21272817` completed successfully (Slurm exit code 0) in 8 minutes 47 seconds. The fitted candidate retains model ID `STRUCTURED_A3_FULLFIT`, uses the unchanged 34-predictor specification, and covers 2025-W01 through 2026-W44. The occurrence and count optimizers both report success. The causal front-feature audit passed for all 963,552 node-week rows, with zero same-week/future history uses, zero missing history cutoffs, zero duplicate node-week rows, and zero nonfinite feature values.

The candidate model SHA-256 is `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b`. Its output manifest records 346 artifacts and has SHA-256 `52205515e55e42de2ede04259913aac5bb2093fe8b7a5ff98fd41fc4824e73d7`; all 288 weekly GeoTIFF tasks are marked complete and six spatial spot checks passed. This is a descriptive fitted-period product, not an independent validation. No P1-P7 scientific qualification or production promotion was performed. The rendering environment emitted NumPy constant-correlation warnings and CRS authority labels were not independently normalized because of the previously recorded PROJ environment limitation; the workflow completed, and its raster spot checks passed.

### Output-path incident and repair

The first Task 2E submission, job `21272802`, used environment-variable names that the wrapper does not read. It therefore wrote to the pre-existing October refresh output path while reading the older October observation file and the new W44 feature bundle. Inspection confirmed the older source checksum was `13ada45bf760f4690a64ebcd147b5743b23527c60650e635dcf1d071eb63653e`; that job did not change either source CSV. The mismatch was identified before full-fit submission. The candidate Task 2E job was then submitted with the wrapper's actual `STGNN_REFRESH_ROOT` and `STGNN_OBSERVATION_PATH` names and wrote to the isolated W44 candidate path above.

The October derived refresh output was rebuilt by Task 2E job `21272837` from its still-present October source and matching, untouched October Task 2A bundle. The rebuilt manifest again identifies the October source checksum and the original bundle's 2026-W39 response endpoint. No pre-run backup of the October derived output was available, so byte-for-byte restoration of its former generated files cannot be claimed; the existing source and Task 2A inputs were preserved, and the derived output was regenerated from them. The October source, corrected November source, W16 frozen artifacts, W29 full-fit model, and active production configuration were not modified.

### Isolation, decision, and validation

After execution, the W29 full-fit model remained at SHA-256 `1cb694f4323ac2d05d973b5631539bd4e3a95ed3ffe3a7405a9e35c6b377092e`, and the active production configuration remained at SHA-256 `f51038b5fe553f1281418d7ed2c9f1060ca8fe32957708c80bbc7332b89b1e3d`. No production pointer was changed and no candidate artifact was promoted. Atlas reported 4.5 TB available on the project filesystem after execution.

The source-integrity decision remains `OBSERVATION_SOURCE_CORRECTION_VERIFIED` for the current source checksum. Input readiness remains `REFRESH_INPUT_READINESS_ESTABLISHED` under the user's explicit acceptance of W44 as provisional and of the documented historical limitations. The candidate is ready for review, but is not production-qualified. Targeted validation consisted of wrapper `bash -n` checks, source and output manifest checks, candidate model status and checksum checks, leakage and raster spot checks, and confirmation that the frozen W29 model and production configuration checksums were unchanged. Package-wide tests, model qualification, independent prospective evaluation, and production workflows were not run because they are outside the candidate-review boundary.
