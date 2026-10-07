# Structured A3 interpretation visual revision

This revision is visualization/reporting only. It does not refit the model, alter coefficients, change predictor selection, recompute permutation importance, change effect-response values, modify GeoTIFF predictions, or add validation claims.

The revised renderer orders coefficient plots by absolute standardized magnitude, adds full and non-front permutation-importance views, separates effect-response curves by response type, documents the exact effect-response reference profile, retains the combined seasonal contribution, and generates a figure index plus compact animation QA table.

`animate_prediction_geotiffs()` reads the weekly GeoTIFFs frame-wise, parses and sorts epidemiological weeks, uses a fixed legend scale, overlays canonical administrative boundaries, and writes GIF output through the dependency-free `gif_from_png_frames.py` helper. MP4 is attempted only when `ffmpeg` is available.

Example:

```r
source("analysis/structured_a3_fullfit/scripts/animate_prediction_geotiffs.R")
animate_prediction_geotiffs(
  raster_dir = "/project/disease_ecology/STGNN-output/structured_a3_fullfit/geotiff/occurrence",
  output_file = "/project/disease_ecology/STGNN-output/structured_a3_fullfit/interpretation_revised/animation/structured_a3_p_occurrence_2025_W01_to_2026_W29.gif",
  value_label = "P(recorded detection)",
  title_prefix = "Structured A3",
  fps = 4,
  limits = c(0, 1)
)
```
