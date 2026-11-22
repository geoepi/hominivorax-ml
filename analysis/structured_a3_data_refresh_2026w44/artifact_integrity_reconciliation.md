# W44 artifact integrity and execution reconciliation

Date: 2026-11-20
Scope: manifest checksum accounting and output-path safeguards only. No model configuration, predictions, candidate artifacts, frozen artifacts, or production pointers were changed.

## Manifest discrepancies

Candidate root: `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44`. The output CSV manifest remains SHA-256 `52205515e55e42de2ede04259913aac5bb2093fe8b7a5ff98fd41fc4824e73d7`, with 346 recorded artifacts. The candidate model remains SHA-256 `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b`.

| File | Manifest-recorded value | Current value during investigation | Cause |
|---|---|---|---|
| `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/fullfit_products/logs/fullfit_21272817.out` | 2,141 bytes; SHA-256 `86696c09a5d031c764d5bcbf2677e8032d5f3a04bdcc2fb62ee460d86c6117db` | 2,274 bytes; SHA-256 `e25a83a76ca3931c44648cd7c5e38d6b605cd6edd5528c9339d654ed18afc60c`; mtime 2026-11-19 11:34:18.979 -0600 | The finalizer hashed the active Slurm stdout file before `main()` printed its final status JSON. Slurm continued writing the log after the hash. This is an execution-log timing difference, not a changed scientific product. |
| `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/fullfit_products/structured_a3_fullfit_output_manifest.json` | 189 bytes; SHA-256 `1864f1f6d47078545887af430256a75d58fec305e88348b2597c2222640ac6ea` | 189 bytes; SHA-256 `fddfbe5097ba08433872af499711568e7ecf17d5b4aed874ff1f4e31c5a73f53`; mtime 2026-11-19 11:34:18.833 -0600 | The finalizer wrote a first CSV/JSON pair, created the report, then rebuilt the CSV inventory and rewrote the JSON. The CSV row therefore captured an earlier JSON version. The JSON also refers to the CSV hash, so including either master manifest inside the inventory creates a circular/stale ordering dependency. |

Slurm job `21272817` completed with exit `0:0`, elapsed 8:47, and ended at 11:34:19. The log and JSON modification times immediately preceded job completion. The model checksum independently matches the recorded W44 model checksum. No evidence indicates a scientific artifact changed unexpectedly. The historical manifest is preserved unchanged; this report reconciles its limitations without rewriting it.

## Output-path incident

Task 2E job `21272802` completed while writing to `/project/disease_ecology/STGNN-output/refresh_2026-10-17/revised_model_data`. The wrapper accepted `STGNN_REFRESH_ROOT` and `STGNN_OBSERVATION_PATH`, but it silently supplied October defaults when those names were absent. It also defaulted the source bundle and previous Task 2D root, created the output log directory before validation, and did not reject populated destinations. The job log and regenerated October manifest establish the effective October observation SHA-256 `13ada45bf760f4690a64ebcd147b5743b23527c60650e635dcf1d071eb63653e` and 2026-W39 endpoint. Job `21272811` used the supported W44 root and November observation source and produced the isolated candidate at `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/revised_model_data`.

The exact incorrectly named environment variables from job `21272802` cannot be recovered: Slurm retained a submit line with `--export=ALL`, but no exported-variable snapshot. The confirmed failure mechanism is the wrapper's defaults and ignored unrecognized names; the exact misspellings are not inferred. The October derived products were regenerated from their preserved source and Task 2A inputs, but byte-for-byte restoration of their pre-run generated files cannot be established.

## Safeguards implemented

- Added `scripts/w44_execution_preflight.py` with per-workflow `STGNN_*` allowlists, explicit path validation, source hashes, vintage checks, and output-directory guards. Only the `STGNN_*` namespace is inspected for unsupported configuration.
- Task 2A now resolves `STGNN_OUTPUT_ROOT` and `STGNN_REFRESH_ROOT` as explicit aliases and rejects conflicts. The existing raw-stage continuation is retained only when the raw artifacts are complete and downstream outputs remain absent or empty.
- Task 2E requires explicit output, source, previous-domain, observation, and boundary paths plus declared observation and Task 2A feature-manifest SHA-256 values. The destination must be new or empty; no October fallback or Task 2E resume is provided. The R script independently rechecks the declared hashes and required inputs before creating output folders.
- Full-fit execution requires explicit source and output paths, checks the Task 2E response/observation manifest, causal-front manifest, frozen A3 anthropogenic/soil checksums, and canonical mask, and rejects populated new-run destinations. A completed fit can resume rendering/finalization only with `STGNN_RESUME_AFTER_FIT=1` and matching input paths, hashes, and horizon.
- Full-fit finalization creates the report before collecting artifacts, writes the CSV inventory once, excludes `logs/` and both master manifests, records the CSV checksum in JSON, and writes external SHA-256 sidecars for both master manifests. The historical W44 manifest was not regenerated.

## Validation and preservation

- Focused synthetic preflight tests: 12 passed.
- Focused master-manifest test: 1 passed.
- Python compilation: passed.
- Bash syntax checks for Task 2A, Task 2E, and full-fit wrappers: passed.
- Repository hygiene check: passed.
- R parsing was not run because the local Windows and Ubuntu WSL runtimes do not provide `Rscript`; R path checks and write ordering received source review.
- No model fitting, Slurm job, production qualification, candidate output write, or production promotion was performed for this engineering task.

Final read-only Atlas checks through the approved WSL/Ubuntu wrapper confirmed these values:

| Artifact | SHA-256 |
|---|---|
| W44 candidate model `fullfit_products/model/fullfit_a3_model.json` | `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b` |
| Preserved W44 master CSV manifest | `52205515e55e42de2ede04259913aac5bb2093fe8b7a5ff98fd41fc4824e73d7` |
| Current W44 master JSON manifest (known stale inventory entry) | `fddfbe5097ba08433872af499711568e7ecf17d5b4aed874ff1f4e31c5a73f53` |
| Current W44 Slurm log (expected to differ from an in-job hash) | `e25a83a76ca3931c44648cd7c5e38d6b605cd6edd5528c9339d654ed18afc60c` |
| Cartographic `figure_manifest.csv` | `b8c41cb95eda295c2cc199bb7902b0480c70cd0e98e092c17bed8261bada789c` |
| Cartographic `figure_manifest.json` | `0c4f3adf00d084298dc492d26d0b018043c9f082f9de12f2c340cf42a22fdd50` |
| Frozen W16 `final_a3_model.json` | `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e` |
| Frozen W16 evaluation manifest | `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61` |
| Pre-existing W29 full-fit model | `1cb694f4323ac2d05d973b5631539bd4e3a95ed3ffe3a7405a9e35c6b377092e` |
| Active production configuration | `f51038b5fe553f1281418d7ed2c9f1060ca8fe32957708c80bbc7332b89b1e3d` |
| Frozen A3 feature manifest | `6c2082795bfeee4dc5bf1f6016f6a00c1e96e53a91a512f3b5e7251f4fb92a20` |
| Anthropogenic feature input | `cb9c6275141cdad33f3563b1c4125d6f97afd7381325a71dcf20d5e1e76e26c6` |
| Soil feature input | `58fcd1314c91f4d792ee221e9d9b7d9d01676087ea953b81a602dc2345bfd4b9` |

The cartographic aggregate manifest hashes match their recorded values; the 148 figure files were not rehashed individually. No candidate prediction file, W16 artifact, W29 artifact, or production configuration was written during this task.

Engineering change classification: **D**, because the diff changes HPC execution paths and data-vintage/output safety controls. The change does not establish scientific qualification; the candidate remains `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.
