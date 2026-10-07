# Task 2A production dataset

Status: verified on Atlas in SLURM job `20839532`. The authoritative runtime artifacts are outside Git under `/project/disease_ecology/STGNN-output/model_data/`.

## Contract

The target is 133 ISO weeks from 2024-W01 through 2026-W29 on the fixed Task-1 environmental intersection domain of 16,756 nodes. For node-week `(i,t)`, `detection_count` is the number of recorded detections assigned to that cell and `presence` is one exactly when the count is positive. A zero means no recorded detection, not confirmed biological absence.

The raw arrays are:

| Artifact | Shape |
|---|---:|
| `dynamic_features.npy` | `[133, 16756, 12]` |
| `dynamic_history_features.npy` | `[185, 16756, 12]` |
| `static_features.npy` | `[16756, 10]` |
| `targets_count.npy` | `[133, 16756]` |
| `targets_presence.npy` | `[133, 16756]` |

The 24-feature modeling order is:

1. `era5_mintemp`
2. `era5_soilmoist`
3. `era5_lai_low`
4. `agera5_relhum_min`
5. `era5land_tmean`
6. `era5land_soiltemp_l1_mean`
7. `era5land_soiltemp_l2_mean`
8. `era5land_soilwater_l1_mean`
9. `era5land_soilwater_l2_mean`
10. `era5land_surface_pressure_mean`
11. `era5land_lai_high_mean`
12. `era5land_lai_low_mean`
13. `cattle_density`
14. `goat_density`
15. `sheep_density`
16. `horse_density`
17. `pig_density`
18. `cattle_density_imputed`
19. `goat_density_imputed`
20. `sheep_density_imputed`
21. `horse_density_imputed`
22. `pig_density_imputed`
23. `week_sin`
24. `week_cos`

Coordinates remain in node metadata and are excluded from the primary predictor tensor. Response lags are excluded.

## Livestock edge-gap rule

All 16,756 canonical nodes are retained. Missing aligned livestock values are completed independently by species using the geographically nearest canonical node with a valid aligned density value. No response or environmental variable is used; zero filling and node removal are prohibited.

The five binary provenance indicators identify imputed values. The donor table is `raw/livestock_imputation_provenance.parquet` and records node, species, donor node, donor distance, and donor density.

| Species | Imputed nodes | Fraction | Mean donor distance (km) | Maximum (km) | >50 km |
|---|---:|---:|---:|---:|---:|
| cattle | 11 | 0.07% | 0.0906 | 0.2057 | 0 |
| goat | 11 | 0.07% | 0.0906 | 0.2057 | 0 |
| sheep | 11 | 0.07% | 0.0906 | 0.2057 | 0 |
| horse | 142 | 0.85% | 0.0951 | 0.3782 | 0 |
| pig | 15 | 0.09% | 0.0731 | 0.2057 | 0 |

The completed density variables receive `log1p` before fold-specific standardization. The five indicators remain 0/1 and are not log-transformed.

## Warm-up and QA

The dataset provides 52 preceding environmental weeks, giving 185 history weeks from 2023-W01 through 2026-W29. All dynamic and completed static values are finite; no environmental node-week has unexplained missingness. Presence equals `count > 0`, counts are nonnegative, and node ordering matches the Task-1 node table.

Across all 2,228,548 target node-weeks, there are 34,129 positive node-weeks (1.53%). In the 107-week development period there are 25,563 positive node-weeks (1.43%).

The positive development counts have mean 4.0272, median 2, variance 18.9411, maximum 72, and variance/mean 4.7033, supporting explicit overdispersion diagnostics while not deciding the later primary model architecture.

Raw distributions, missingness, response frequencies, livestock provenance, checksums, and correlation matrices are in `model_data/diagnostics/` and `model_data/manifests/`.

## Redundancy

All 12 environmental predictors are retained. Development-period diagnostics flagged nine pairs at absolute correlation at least 0.90; the strongest were:

- ERA5-Land soil temperature layers 1 and 2: Pearson 0.9958, Spearman 0.9939.
- ERA5-Land mean temperature and soil temperature layer 1: Pearson 0.9822, Spearman 0.9729.
- ERA5-Land mean temperature and soil temperature layer 2: Pearson 0.9783, Spearman 0.9709.
- ERA5 soil moisture and ERA5-Land soil water layer 1: Pearson 0.9580, Spearman 0.9580.

No predictor was removed or combined in Task 2A.
