# Qualification report

## Status

The refresh is not qualified. Administrative decision: REFRESH_BLOCKED_BY_INPUT_DATA.

## Stage results

| Stage | Status | Evidence |
| --- | --- | --- |
| A: input and compatibility audit | Complete; blocked | New observations have no documented complete-week cutoff and contain substantial unexplained revisions in the original fit horizon. |
| B: frozen specification audit | Complete | Public freeze, predictor schema, source provenance, model parameters, software records, validation entry points, and production artifacts were checked. |
| C: candidate refresh | Not started | The input stop condition was met before any model execution. |
| D: qualification | Not run | No candidate artifact exists to evaluate. |

## Qualification criteria not evaluated

Successful execution, output contracts, candidate artifact integrity, reproducibility, downstream compatibility, and scientific acceptance remain untested because there is no candidate. No existing criterion was weakened or redefined.

The repository qualification plan records P0-P7 procedures. This audit does not authorize a P1-P7 run by itself. The original frozen P0 artifact and the pre-existing Atlas fullfit are separate objects and remain unchanged by this task.

## Validation record

The change set is documentation and machine-readable audit metadata only (Class A). The changed files were reviewed; JSON manifests were parsed locally. No package tests, model fit, Slurm execution, or production workflow was run. These omissions follow the Stage A stop gate, not a passing qualification result.

No Atlas quota check was made because execution stopped before any large output was created. No Slurm job IDs, logs, exit codes, fitted candidate artifacts, or candidate output paths exist.

## Corrected-source re-audit — 2026-11-19

The corrected observation snapshot was re-audited using the existing Python implementation and independent base-R cross-check. Both agree that 2,263 exact-decimal observation-key groups remain across 167,030 records, including 975 in the original W16 horizon. The current source integrity decision is `OBSERVATION_DUPLICATES_REMAIN`; overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA`. W44 completeness and historical revision provenance remain unresolved, and the separate W29 artifact-lineage question remains open. Consequently, Stage C and Stage D remain not started/not run and model fitting must not begin. See `observation_corrected_source_reaudit.md` for the source checksum, aggregate results, limitations, and focused validation record. The earlier source-specific audit and results remain preserved separately.

## Latest source verification — 2026-11-19

A minimal R 4.5.1 check of the source at the authoritative path (SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`) found 164,767 rows, 164,767 unique observation keys, and zero redundant keys. The source-specific decision is `OBSERVATION_SOURCE_CORRECTION_VERIFIED`; the duplicate-related blocker is closed for this source checksum. Overall readiness remains `REFRESH_BLOCKED_BY_INPUT_DATA` because reporting completeness, historical revision provenance, and W29 artifact lineage remain unresolved. Stages C and D remain not started/not run.
