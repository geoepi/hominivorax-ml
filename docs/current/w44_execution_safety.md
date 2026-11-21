# W44 execution safety

The Task 2A, Task 2E, and Structured A3 full-fit wrappers use explicit paths and run `scripts/w44_execution_preflight.py` before creating outputs. Unsupported names in the `STGNN_*` configuration namespace stop execution with a diagnostic. Other environment variables are not inspected.

## Task 2A

Set exactly one of `STGNN_OUTPUT_ROOT` or `STGNN_REFRESH_ROOT`, or set both to the same absolute path. A conflict or missing/empty path is an error. Also set `STGNN_ENVIRONMENTAL_ROOT`, `STGNN_TEMPLATE_PATH`, and `STGNN_PYTHON_ENV`. `STGNN_ANALYSIS_START` and `STGNN_ANALYSIS_END` are optional.

The default run requires `model_data` to be absent or empty. The existing raw-stage continuation is selected with `STGNN_SKIP_DATASET_BUILD=1`; it requires all raw Task 2A artifacts and refuses to continue if pipeline outputs or `task2a_manifest.json` already exist. Use `0` for a new raw build. The R and Python stages validate their inputs before creating or writing model outputs.

## Task 2E

Set `STGNN_REFRESH_ROOT`, `STGNN_SOURCE_OUTPUT_ROOT`, `STGNN_PREVIOUS_OUTPUT_ROOT`, `STGNN_OBSERVATION_PATH`, `STGNN_BOUNDARY_PATH`, `STGNN_EXPECTED_OBSERVATION_SHA256`, and `STGNN_EXPECTED_FEATURE_MANIFEST_SHA256`. Hash values must match the selected files. `STGNN_BOUNDARY_LAYER` defaults to `study_states`; analysis and response horizon variables retain their declared workflow defaults unless explicitly set.

The output is always `${STGNN_REFRESH_ROOT}/revised_model_data`. It must be absent or empty. Task 2E does not resume into a populated output. The preflight prints the selected paths, hashes, horizons, and output state before execution. Do not pass Task 2E path aliases through unrelated variable names.

## Full-fit products

Set `STGNN_FULLFIT_OUTPUT_ROOT`, `STGNN_MODEL_OUTPUT_ROOT`, `STGNN_ANTHROPOGENIC_FEATURES`, `STGNN_SOIL_FEATURES`, `STGNN_FULLFIT_MASK`, `STGNN_EXPECTED_OBSERVATION_SHA256`, `STGNN_RESPONSE_START`, and `STGNN_RESPONSE_END`. Set `STGNN_FRONT_FEATURES` for an existing feature table, or set `STGNN_BUILD_A3_FRONT_FEATURES=1` with `STGNN_FRONT_FEATURE_ROOT` for a new table. All feature inputs are checked against the Task 2E vintage and the committed A3 feature manifest.

A new fit requires an absent or empty `STGNN_FULLFIT_OUTPUT_ROOT`. After a completed fit, set `STGNN_RESUME_AFTER_FIT=1` to continue the renderer and finalizer. Resume is accepted only when the completed fit manifest's data paths and checksums and response horizon agree with the selected inputs. Immutable repository manifests are matched by checksum across checkouts. Older completed fits may omit the newer feature-manifest entries; their source data files must still match, and the current manifests must independently validate those inputs. A partial fit without a completed fit manifest is not resumable through this wrapper and must be reviewed before any new output path is selected.

The full-fit artifact CSV excludes Slurm logs and both master manifest files. The JSON master manifest records the CSV SHA-256; separate `.sha256` sidecars checksum the CSV and JSON. Do not rewrite the historical W44 manifest to reconcile earlier discrepancies. See [`artifact_integrity_reconciliation.md`](../../analysis/structured_a3_data_refresh_2026w44/artifact_integrity_reconciliation.md).
