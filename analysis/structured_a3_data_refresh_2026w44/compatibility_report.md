# Input compatibility and historical revision report

## Decision

Stage A found a material observation-input blocker. The source has observations through 2026-W46, but the release does not identify its latest complete observation week. The same source revises most keys in the frozen 68-week fit horizon, with no release note or method history explaining the differences. Under the controlled-refresh stop rule, model execution is not authorized until these points are resolved.

## Observation source

The new file has the expected four columns: date, host, lon, and lat. It contains 167,078 rows, no blank fields, no invalid dates, and globally valid coordinates for all rows. Dates span 2022-02-10 through 2026-11-13. The latest observed week is W46, with 300 rows; this is not a completeness declaration. The release date label is November 13, while the file modification time is November 18. The audit found no release-specific complete-week manifest or completeness metadata.

The earlier audit reported 2,295 exact repeated complete rows overall and 980 in the original fit horizon. A follow-up source-precision audit confirms those complete-row counts and establishes that the source has 2,311 duplicated `(date, lon, lat)` key groups overall and 988 in the original fit horizon. At exact decimal precision these comprise 4,622 / 1,976 participating rows, respectively; each key is a pair, so the redundant-row counts are 2,311 / 988. The additional 16 key groups overall (eight in the training horizon) repeat date and coordinates with different host values. Raw-character, exact-decimal, float64, and reconstructed previous-method key counts agree; parsing and date normalization did not create the duplicates.

The exact prior executable was not retained. The available report identifies a direct source-file comparison on ISO date, host, and numerically normalized coordinates; this follow-up reconstructs that method with pandas and finds the earlier figures match complete-row duplicate groups and redundant rows. As all duplicate groups are pairs, those two count definitions are numerically identical here; the previous report did not say which one it displayed. The full comparison table, precision diagnostics, code, and limitations are in `observation_duplicate_precision_audit.md` and its linked aggregate outputs. Existing refresh code reports duplicates and includes every row in aggregation. The source documentation still does not establish whether repeated records represent separate cases, duplicate ingestion, or another process. No deduplication or imputation was applied.

See input_manifest.json for source size, timestamps, checksums, schema, and aggregate checks.

## Environmental products

All 12 frozen dynamic predictors have 252 contiguous weekly GeoTIFFs from 2022-W01 through 2026-W44. The 2026-W44 sidecars record all seven dates from October 26 through November 1 and the weekly-v3-support-mask aggregation version. Every W44 GeoTIFF checksum matches its sidecar output checksum. W29 and W44 variable specification hashes and template hashes agree for all predictors.

After aligning the one-based stored node row and column indices, all 10,037 A3 nodes have finite values for all 12 W44 predictors. The current weekly rasters also match the frozen raw feature arrays exactly across all 8,190,192 values in the original fit horizon. There were zero missing or changed values in that comparison.

The raster dimensions and affine transform match the canonical mask. The Albers projection parameters, WGS84 datum, and kilometre units match; WKT labels differ. Atlas Python repeatedly reported that proj.db was unavailable, so EPSG authority normalization was not independently confirmed. This environment limitation is recorded in the inventory.

Processing sidecars preserve weekly statistics, selected daily paths/checksums, input fingerprints, and aggregation metadata. Provider release-time or revision-lag metadata was not established, so the environmental audit confirms product processing continuity and support, not the upstream vintage of every source product.

## Historical observation revisions

The multiset comparison used ISO date, host, and numerically normalized longitude and latitude, preserving multiplicity and recording no row-level values.

For 2025-W01 through 2026-W16, the frozen source has 79,257 rows and the new source has 91,993. Only 15,988 key instances match; 76,005 are added or changed in the new source and 63,269 are removed or changed from the frozen source. Against the October 17 snapshot, 23,759 key instances match; 68,234 are added or changed and 67,222 are removed or changed.

These counts identify substantial historical revision. They do not determine which snapshot is correct. The source directory contains no release notes explaining the revisions. The frozen source path is labeled 2027-07-31 although its content ends on 2026-07-31 and its modification time predates the audit.

Detailed counts are in historical_revision_summary.json.

## Compatibility result

| Input surface | Result |
| --- | --- |
| Observation columns and basic parsing | Compatible |
| Observation reporting completeness | Unresolved; blocking |
| Exact repeated observation rows | Present; semantics unresolved |
| Historical observation revisions in fit horizon | Material and unexplained; blocking |
| Environmental weekly coverage through W44 | Complete for all 12 frozen dynamic predictors |
| Environmental values across frozen fit horizon | Exact match to frozen raw bundle |
| A3 spatial-node support at W44 | All 10,037 nodes supported |
| CRS authority normalization | Limited by missing proj.db; grid and projection parameters agree |

No model execution, candidate artifact generation, or data transformation was performed. Restricted rows and raster values remain on Atlas.

## Corrected-source re-audit — 2026-11-19

The preceding observation counts describe the original updated-source snapshot with SHA-256 `8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc`. The source at the same path has since been corrected; its SHA-256 is `2f9cf04ffe01712b8e5498d809f542d159ff1cb33ae8b567aa6644e9c4f05de5`. The current snapshot contains 167,030 rows and 2,263 exact-decimal `(date, lon, lat)` duplicate groups (4,526 participating rows; 2,263 redundant rows), including 975 groups in the original W16 horizon. Python and independent R metrics agree. The old immutable source was unavailable, so aggregate differences do not establish which individual groups were removed or retained. The detailed re-audit and current decision are in `observation_corrected_source_reaudit.md` and its aggregate outputs.

The corrected snapshot has no newly identified schema, missingness, date-validity, or coordinate-validity problem. The duplicate-key blocker remains, as do undocumented W44 reporting completeness and unexplained historical revisions. The previous source-specific counts above remain for audit traceability and must not be read as counts for the corrected snapshot.
