# Qualification report

## Current status

Input readiness is established as `REFRESH_INPUT_READINESS_ESTABLISHED` under the user's explicit dispositions. The W44 candidate data refresh and descriptive full-fit completed and passed the recorded candidate artifact checks. The candidate is ready for review; independent qualification and production promotion have not occurred.

## Current stage results — candidate review boundary

| Stage | Status | Evidence |
| --- | --- | --- |
| A: input and compatibility audit | Complete; readiness accepted for this controlled refresh | The corrected source checksum was verified, named-column compatibility was confirmed, and the user accepted W44 provisionally with reporting completeness and historical revisions retained as limitations. |
| B: frozen specification audit | Complete | Frozen predictors, response contract, model parameters, and existing production artifacts were checked. |
| C: candidate refresh | Complete | Task 2A job 21272766 built the candidate environmental bundle; Task 2E job 21272811 built the refreshed W44 response from the authoritative source. |
| D: candidate artifact checks | Complete for review; production qualification not performed | Full-fit job 21272817 completed, optimizer success flags were true, the causal-history leakage audit passed, and the completed output manifest records 346 artifacts. |

This status authorizes candidate review only. It does not certify W44 reporting completeness, explain historical revisions, establish independent prospective performance, or authorize production promotion. The separate W29 lineage question remains deferred.

## Initial audit status (historical; retained for traceability)

At the end of the original read-only audit, the administrative decision was `REFRESH_BLOCKED_BY_INPUT_DATA`.

## Stage results

| Stage | Status | Evidence |
| --- | --- | --- |
| A: input and compatibility audit | Complete; blocked at that time | New observations had no documented complete-week cutoff and contained substantial unexplained revisions in the original fit horizon. |
| B: frozen specification audit | Complete | Public freeze, predictor schema, source provenance, model parameters, software records, validation entry points, and production artifacts were checked. |
| C: candidate refresh | Not started | The input stop condition was met before any model execution. |
| D: qualification | Not run | No candidate artifact exists to evaluate. |

## Qualification criteria not evaluated in the original audit

Successful execution, output contracts, candidate artifact integrity, reproducibility, downstream compatibility, and scientific acceptance remain untested because there is no candidate. No existing criterion was weakened or redefined.

The repository qualification plan records P0-P7 procedures. This audit does not authorize a P1-P7 run by itself. The original frozen P0 artifact and the pre-existing Atlas fullfit are separate objects and remain unchanged by this task.

## Validation record

The change set is documentation and machine-readable audit metadata only (Class A). The changed files were reviewed; JSON manifests were parsed locally. No package tests, model fit, Slurm execution, or production workflow was run. These omissions follow the Stage A stop gate, not a passing qualification result.

No Atlas quota check was made because execution stopped before any large output was created. No Slurm job IDs, logs, exit codes, fitted candidate artifacts, or candidate output paths exist.

## Corrected-source re-audit — 2026-11-19

The corrected observation snapshot was re-audited using the existing Python implementation and independent base-R cross-check. Both agree that 2,263 exact-decimal observation-key groups remain across 167,030 records, including 975 in the original W16 horizon. The current source integrity decision is `OBSERVATION_DUPLICATES_REMAIN`; overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA`. W44 completeness and historical revision provenance remain unresolved, and the separate W29 artifact-lineage question remains open. Consequently, Stage C and Stage D remain not started/not run and model fitting must not begin. See `observation_corrected_source_reaudit.md` for the source checksum, aggregate results, limitations, and focused validation record. The earlier source-specific audit and results remain preserved separately.

## Latest source verification — 2026-11-19

A minimal R 4.5.1 check of the source at the authoritative path (SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`) found 164,767 rows, 164,767 unique observation keys, and zero redundant keys. The source-specific decision is `OBSERVATION_SOURCE_CORRECTION_VERIFIED`; the duplicate-related blocker is closed for this source checksum. Overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA` because reporting completeness, historical revision provenance, and W29 artifact lineage remain unresolved. Stages C and D remain not started/not run.

## Controlled refresh resumption — 2026-11-19

The user authorized continuation after accepting the provisional W44 endpoint and the documented limitations. Stage A is now `REFRESH_INPUT_READINESS_ESTABLISHED`; Stage B remains verified. Stages C and D are pending. This does not qualify or authorize the candidate for production. The original W16 frozen artifact and existing W29 fullfit remain separate and unchanged.

## Candidate execution and review status — 2026-11-19 (latest)

Stages C and the candidate-level artifact checks in Stage D are complete. Task 2A job `21272766`, Task 2E job `21272811`, and full-fit job `21272817` completed successfully. The candidate response manifest matches the current observation checksum and contains zero duplicate source keys. The candidate fit spans 2025-W01 through 2026-W44; both model optimizer success flags are true, the causal-history leakage audit passed for all 963,552 node-week rows, and the 346-artifact output manifest is complete with six passing spatial spot checks.

The result is ready for review only. W44 remains provisional and is not certified complete. The full-fit products describe the fitted period and do not provide independent predictive qualification. No P1-P7 qualification, production release, or promotion was performed. The original stop-gate reports and dated intermediate statuses above remain in the record as historical evidence; this latest status supersedes their earlier statements that candidate execution had not started. The Task 2E output-path incident and the reconstruction of the prior October derived output are documented in `decision_report.md`.
