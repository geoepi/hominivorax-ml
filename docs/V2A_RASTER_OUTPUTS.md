# V2-A Raster Outputs

Task 3E writes analysis-ready rasters under
`/project/disease_ecology/STGNN-output/v2_rasters/` from the persisted,
development-frozen `STGNN-Hurdle-V2A` prediction artifact. No model is fit by
the Task 3E scripts.

## Canonical grid and mask

The raster geometry is copied from the validated environmental template
`/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif`:

- 202 rows x 293 columns;
- 24.995 x 24.9437 projected-km cell resolution;
- Albers Equal Area CRS used by the production grid;
- extent `[-4361.4109, 2962.1297, -2202.9997, 2835.6188]`;
- `FLT4S` GeoTIFF values with explicit nodata `-9999`.

The environmental template supports 16,756 cells. The revised V2-A modeled
domain contains 10,037 persisted nodes. Task 3E uses the authoritative
`raster_cell`, `row`, and `column` fields in
`revised_model_data/raw/nodes.parquet` as the modeled valid-cell mask. The
template geometry is retained exactly; cells outside the 10,037 modeled nodes
remain nodata. No spatial grid is reconstructed from longitude/latitude and no
interpolation is performed.

## Prediction source and reconstruction

`scripts/task3e_prepare_inputs.py` selects the existing M1 / penalty 0.01
rows from `v2_model/validation/validation_predictions.parquet`. The persisted
historical pseudo-prospective folds are used as follows:

- 2026-W17 through 2026-W22: fold 5;
- 2026-W23 through 2026-W29: fold 6.

Both folds are labeled historical pseudo-prospective and non-independent. The
script joins those rows to the persisted node table and exports an explicit
input manifest. It performs no refitting, threshold tuning, feature changes,
or model selection.

## Variables and naming

The preferred full range, 2026-W17 through 2026-W29, is written for:

- `probability/stgnn_v2a_probability_YYYY-Www.tif`: probability of a
  recorded detection;
- `expected_count/stgnn_v2a_expected_count_YYYY-Www.tif`: unconditional
  expected recorded detection count, `E[Y]`;
- `conditional_count/stgnn_v2a_conditional_positive_count_YYYY-Www.tif`:
  conditional positive count, `E[Y | Y > 0]`.

The GeoTIFFs use DEFLATE compression and tiled output. Values are not
quantized. Raster metadata are stored in
`manifests/task3e_raster_metadata.csv` and `.json`.

## Pseudo-nowcast handling

Pre-outcome pseudo-nowcast prediction-only rasters are written for 2026-W23
and 2026-W26 under `pseudo_nowcast/`:

- `stgnn_v2a_preoutcome_probability_YYYY-Www.tif`;
- `stgnn_v2a_preoutcome_expected_count_YYYY-Www.tif`.

Observed detections are stored separately in the input overlay table and are
never written into these rasters. The scored figure adds observations as a
visual overlay only.

## Provenance and QA

`manifests/task3e_raster_manifest.json` records model, grid, source-artifact,
week, output, and checksum provenance. `manifests/task3e_checksums.csv`
contains SHA-256 checksums for all rasters and figures. The QA report records
node/mask agreement, raster geometry, masked-cell handling, sampled source
value agreement, probability/count ranges, pseudo-nowcast separation, and
figure completion.
