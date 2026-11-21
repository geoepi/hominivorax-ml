# Structured A3 interpretation visual revisions

This directory contains visualization-only revisions for the persisted Structured A3 full-fit products. The scripts read existing coefficient, permutation-importance, effect-response, seasonality, and weekly GeoTIFF artifacts; they do not refit the model or alter numerical products.

Run on Atlas with:

```bash
sbatch analysis/structured_a3_fullfit/scripts/run_interpretation_revised.sbatch
```

The renderer writes revised figures, compact tables, animation QA, and GIFs under `/project/disease_ecology/STGNN-output/structured_a3_fullfit/interpretation_revised/`. `animate_prediction_geotiffs.R` is reusable for occurrence, conditional-count, and expected-count GeoTIFF directories. GIFs use the local dependency-free PNG-to-GIF helper; MP4 is generated only when `ffmpeg` is available.

## Full-fit production products

# STRUCTURED A3 full-fit products

This workflow fits the frozen 34-predictor STRUCTURED A3 hurdle model to all
complete predictor-supported response weeks beginning at 2025-W01, then writes
descriptive node predictions, canonical-grid GeoTIFFs, interpretation tables
and figures, nowcast PDFs, and a compact report.

The scientific specification is not changed by this workflow. The fit uses
fixed `theta = 0.7018903965556372`, penalty `0.01`, and objective
`exact_joint_hurdle_nll`. Detection-history features are checked for strictly
prior response use before fitting.

## Execution

The wrapper no longer supplies historical output or input defaults. Before
submitting on Atlas, set `STGNN_FULLFIT_OUTPUT_ROOT`, `STGNN_MODEL_OUTPUT_ROOT`,
`STGNN_FRONT_FEATURES` (or `STGNN_BUILD_A3_FRONT_FEATURES=1` and
`STGNN_FRONT_FEATURE_ROOT`), `STGNN_ANTHROPOGENIC_FEATURES`,
`STGNN_SOIL_FEATURES`, `STGNN_FULLFIT_MASK`,
`STGNN_EXPECTED_OBSERVATION_SHA256`, `STGNN_RESPONSE_START`, and
`STGNN_RESPONSE_END`. `STGNN_REPOSITORY_ROOT` may select the checkout; otherwise
submit from that repository root. See [`W44 execution safety`](../../docs/current/w44_execution_safety.md)
for the validation and path contract.

The new-fit destination must be absent or empty. Slurm logs are written under
`/project/disease_ecology/STGNN-output/logs/`, outside the model output. The
Python `fit` stage produces the model, weekly Parquet archive, summaries, and
interpretation-ready tables. After a completed fit, the R renderer skips
existing weekly GeoTIFFs and regenerates missing/failed spatial products. The
Python `finalize` stage updates the report and output manifests.

To continue rendering/finalization after the fit manifest is complete, set
`STGNN_RESUME_AFTER_FIT=1`. The preflight requires the current data paths,
source checksums, and response horizon to match the completed fit manifest;
immutable repository manifests are compared by checksum across worktrees.
Partial fit output without a completed fit manifest is not resumable through
this wrapper.

Weekly rasters use the exact canonical mask and persisted node-to-cell mapping;
cells outside the 10,037-node domain are explicit NoData. The nowcast period is
the latest six complete supported weeks. Its layout is the established Task
3E exact-cell continuous map design documented in `docs/V2A_MAP_FIGURES.md`
and `scripts/task3e_raster_outputs.R`, adapted to Structured A3 full-fit
predictions. Every PDF is labeled descriptive and non-validation.
