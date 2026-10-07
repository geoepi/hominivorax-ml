# Structured A3 animation geometry correction

## Root cause

The failure was a malformed GIF bitstream, not a raster coordinate reversal. The direct 2026-W29 raster frame generated from the GeoTIFF matched the established nowcast map. The prior dependency-free GIF encoder emitted variable-width LZW codes with a code-size transition one dictionary step too early; a standard decoder failed on the W29 frame with an invalid LZW code. The encoder now uses the decoder-visible dictionary state when selecting each code width.

## Rendering correction

Each frame now reads coordinates and values together with `terra::as.data.frame(r, xy = TRUE, cells = FALSE, na.rm = FALSE)`. No manual row reversal, y-axis reversal, matrix transpose, or x/y swap is performed. Every GeoTIFF is checked against the template for common CRS, extent, resolution, row/column dimensions, and origin. Boundaries are transformed to the raster CRS, the raster extent is fixed across frames, and NoData/background pixels are rendered opaque white.

## Diagnostic evidence

- W29 occurrence static frame: spatial orientation, footprint, high/low pattern, and boundary alignment match the reference nowcast PDF.
- Raster geometry: 202 rows, 293 columns, 24.9950189 by 24.9436560 resolution, 10,037 valid cells.
- Cell identity: 22 cells spanning north, south, east, west, center, high-value, and low-value locations; maximum absolute difference is 0.
- Representative occurrence frames 1, 41, and 81 decode successfully and show weeks 2025-W01, 2025-W41, and 2026-W29.
- All 243 original GeoTIFF hashes match the canonical full-fit output manifest.
