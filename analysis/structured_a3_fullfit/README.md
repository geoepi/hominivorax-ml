# Structured A3 interpretation visual revisions

This directory contains visualization-only revisions for the persisted Structured A3 full-fit products. The scripts read existing coefficient, permutation-importance, effect-response, seasonality, and weekly GeoTIFF artifacts; they do not refit the model or alter numerical products.

Run on Atlas with:

```bash
sbatch analysis/structured_a3_fullfit/scripts/run_interpretation_revised.sbatch
```

The renderer writes revised figures, compact tables, animation QA, and GIFs under `/project/disease_ecology/STGNN-output/structured_a3_fullfit/interpretation_revised/`. `animate_prediction_geotiffs.R` is reusable for occurrence, conditional-count, and expected-count GeoTIFF directories. GIFs use the local dependency-free PNG-to-GIF helper; MP4 is generated only when `ffmpeg` is available.
