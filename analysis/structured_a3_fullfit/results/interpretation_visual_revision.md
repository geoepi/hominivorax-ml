# Structured A3 interpretation visual revision

This revision is visualization/reporting only. It does not refit the model, alter coefficients, change predictor selection, recompute permutation importance, change effect-response values, modify GeoTIFF predictions, or add validation claims.

The revised renderer orders coefficient plots by absolute standardized magnitude, adds full and non-front permutation-importance views, separates effect-response curves by response type, documents the exact effect-response reference profile, retains the combined seasonal contribution, and generates a figure index plus compact animation QA table.

`animate_prediction_geotiffs()` reads the weekly GeoTIFFs frame-wise, derives x/y/value together with `terra::as.data.frame(..., xy = TRUE, cells = FALSE, na.rm = FALSE)`, checks common raster geometry, transforms canonical administrative boundaries to the raster CRS, uses a fixed geographic extent and legend scale, renders opaque white backgrounds/NoData, and writes GIF output through the decoder-synchronized dependency-free `gif_from_png_frames.py` helper. MP4 is attempted only when `ffmpeg` is available.

## Animation geometry correction

The previous direct W29 raster frame already matched the established W29 nowcast map in orientation, footprint, high/low pattern, and boundary alignment. The previous GIF failed a standard GIF LZW decode on the W29 frame, identifying the verified root cause as a code-width synchronization error in the dependency-free encoder. This was not an x/y reversal, north/south row reversal, matrix transpose, or CRS mismatch. The encoder now synchronizes variable-width codes to the decoder-visible dictionary state.

The corrected W29 diagnostic uses a 202-row by 293-column raster with 10,037 valid cells. The persisted `animation_cell_identity_check.csv` contains 22 cells spanning spatial and high/low-value diagnostics; the maximum absolute GeoTIFF-to-animation value difference is zero. The `animation_qa.csv` table records fixed extents/scales, opaque backgrounds, CRS metadata, and representative check status for all three animations.

Example:

```r
source("analysis/structured_a3_fullfit/scripts/animate_prediction_geotiffs.R")
animate_prediction_geotiffs(
  raster_dir = "/project/disease_ecology/STGNN-output/structured_a3_fullfit/geotiff/occurrence",
  output_file = "/project/disease_ecology/STGNN-output/structured_a3_fullfit/interpretation_revised/animation/structured_a3_p_occurrence_2025_W01_to_2026_W29.gif",
  value_label = "P(recorded detection)",
  title_prefix = "Structured A3",
  fps = 4,
  limits = c(0, 0.6)
)
```
