# Observation duplicate and precision audit

## Decision

**Source-integrity decision: `OBSERVATION_DUPLICATES_CONFIRMED_AT_SOURCE`.**

The updated observation CSV contains 2,311 duplicated `(date, lon, lat)` groups at exact numerical decimal precision, with 4,622 rows participating and 2,311 redundant rows beyond the first occurrence. Within the original W16 training horizon, it contains 988 such groups (1,976 participating rows; 988 redundant rows). Every duplicated coordinate key has multiplicity two.

The previously reported 2,295 overall and 980 training-horizon counts are also genuine: they are exact repeated complete source records. They are not the complete count of duplicated `(date, lon, lat)` keys because host is part of a full record but not part of the observation-key contract. Sixteen additional full-dataset coordinate-key groups (eight in the training horizon) have the same date and coordinates but differ in host. This follow-up supersedes the earlier ambiguity while retaining the original values for traceability.

## Scope and source integrity

This was a read-only integrity investigation. No source CSV was changed, no observation-level rows or coordinates were transferred from Atlas, and no model inputs were reconstructed. No model fitting or production qualification was run.

| Dataset | Atlas source | Rows | SHA-256 |
| --- | --- | ---: | --- |
| Updated 2026-11-13 | `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-11-13.csv` | 167,078 | `8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc` |
| Frozen W16 source | `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv` | 136,714 | `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e` |

Both source checksums matched the expected recorded values before parsing and comparison. The historical file name is retained as supplied; its content ends 2026-07-31.

## Previous audit method and reconciliation

The earlier report recorded exact repeated rows in the updated source. The audit's prior committed description identifies the source CSV and a comparison over ISO date, host, and numerically normalized longitude and latitude, preserving multiplicity. Repository and audit-directory searches did not recover the executable that produced the figures. Parser options and whether its displayed quantity was duplicate groups or redundant rows were not recorded.

To reconstruct the described operation, this audit used pandas 3.0.6 with default `read_csv` type inference, standardized dates through `to_datetime().dt.strftime('%Y-%m-%d')`, converted longitude and latitude with `to_numeric().astype('float64')`, and cast host to string. The source has only `date, host, lon, lat`; the reconstruction checked both all four fields and the three-field observation key. There is no evidence that the prior audit applied raster-cell assignment, spatial snapping, CRS conversion, or weekly aggregation. The exact prior executable and its processing order remain unavailable, so the reconstruction is not represented as a verbatim replay.

| Updated source comparison | Subset | Total rows | Unique keys | Duplicate groups | Rows in groups | Redundant rows | Max multiplicity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete raw source record | Entire | 167,078 | 164,783 | 2,295 | 4,590 | 2,295 | 2 |
| Complete raw source record | W16 training horizon | 91,993 | 91,013 | 980 | 1,960 | 980 | 2 |
| Exact-decimal `(date, lon, lat)` key | Entire | 167,078 | 164,767 | 2,311 | 4,622 | 2,311 | 2 |
| Exact-decimal `(date, lon, lat)` key | W16 training horizon | 91,993 | 91,005 | 988 | 1,976 | 988 | 2 |

For a key repeated `k` times, duplicate groups count the key once, rows in duplicate groups count all `k` records, and redundant rows count `k-1`. All groups in these updated-source comparisons are pairs, so duplicate groups and redundant rows happen to have equal values. The earlier 2,295 and 980 values therefore reproduce under either of those two definitions; they do not mean only 2,295 or 980 rows participated.

The previous pandas full-row reconstruction returned the same figures as exact complete raw records. The pandas coordinate-key reconstruction returned 2,311 groups overall and 988 in the training horizon. This is evidence that date/numeric parsing did not create the prior full-row counts and did not alter the exact coordinate-key totals.

## Exact-precision and numeric-parsing results

The audit independently compared complete records and `(date, lon, lat)` using raw character fields, losslessly canonicalized exact decimals, standard float64 coordinates, and the reconstructed pandas method. Python `csv.DictReader` retained every source field as a string for the raw comparison. Decimal canonicalization uses integer digits plus a base-10 exponent, making `-100.123450` and `-100.12345` numerically equal without dropping any nonzero decimal digit.

For the updated source, raw character, exact-decimal, standard float64, and pandas-reconstructed coordinate-key comparisons all return 164,767 unique keys overall and 91,005 in the training horizon. The corresponding duplicate-group totals are 2,311 and 988. The exact-decimal and float64 unique coordinate-value comparisons show no float64 collisions in either axis. Numeric parsing did not change the number of unique keys in these files.

The independent base R cross-check read all source columns as character, verified the same source hashes, and returned the same raw complete-record, raw-key, and exact-decimal key metrics for both releases. Its aggregate output is retained in `observation_duplicate_precision_r_crosscheck.csv`.

### Summary by dataset and temporal subset

The table uses exact-decimal coordinates and the source-local calendar date. The “before” rows are included to make the requested entire / within / after partitions auditable.

| Dataset | Temporal subset | Total rows | Unique keys | Duplicate groups | Rows in groups | Redundant rows | Max multiplicity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Updated 2026-11-13 | Entire | 167,078 | 164,767 | 2,311 | 4,622 | 2,311 | 2 |
| Updated 2026-11-13 | W16 training horizon | 91,993 | 91,005 | 988 | 1,976 | 988 | 2 |
| Updated 2026-11-13 | After W16 horizon | 30,178 | 28,855 | 1,323 | 2,646 | 1,323 | 2 |
| Updated 2026-11-13 | Before W16 horizon | 44,907 | 44,907 | 0 | 0 | 0 | 1 |
| Frozen W16 source | Entire | 136,714 | 136,707 | 4 | 11 | 7 | 4 |
| Frozen W16 source | W16 training horizon | 79,257 | 79,257 | 0 | 0 | 0 | 1 |
| Frozen W16 source | After W16 horizon | 12,549 | 12,543 | 3 | 9 | 6 | 4 |
| Frozen W16 source | Before W16 horizon | 44,908 | 44,907 | 1 | 2 | 1 | 2 |

The historical duplicates are within that historical file. They are not cross-release overlap. Within the original training horizon, the two releases share 53,641 key instances (source-local date plus exact-decimal coordinates); the updated release has 38,352 additional key instances and the historical release has 25,616 additional key instances. Exact complete-record overlap in that horizon is 15,988 instances. These release-overlap quantities are reported separately and are not counted as within-dataset duplicates. The updated release is a replacement snapshot, not an append operation.

## Coordinate representation and rounding diagnostic

Longitude is written with 0–8 fractional decimal places; latitude uses 0–14. The per-precision record distributions are in `observation_coordinate_precision_summary.csv`. Neither source uses scientific notation or trailing fractional zeroes. No coordinate value appears in multiple textual forms that canonicalize to the same exact decimal. Textual equality and exact numerical equality produced the same unique coordinate values and the same `(date, lon, lat)` key counts.

There is variable formatting precision in the source. The audit found no exact values collapsed into the same float64 bin, but cannot infer upstream geocoding accuracy or prove that a source producer never rounded coordinates before this CSV was created. There is no evidence in this CSV of an additional audit-time truncation or rounding step.

Deliberate rounding used exact Decimal quantization with `ROUND_HALF_EVEN`; it is diagnostic only. The updated-source duplicate-group totals at each tested precision are:

| Decimal places | Entire dataset | W16 training horizon |
| ---: | ---: | ---: |
| 10 | 2,384 | 1,012 |
| 9 | 2,384 | 1,012 |
| 8 | 3,456 | 1,476 |
| 7 | 3,948 | 1,624 |
| 6 | 4,476 | 1,881 |
| 5 | 4,672 | 2,058 |
| 4 | 4,989 | 2,268 |
| 3 | 6,789 | 3,814 |
| 2 | 10,784 | 6,689 |

No tested precision reproduces 2,295 overall or 980 in the training horizon as coordinate-key duplicate groups. Even rounding to 10 or 9 decimal places adds 73 duplicate groups overall and 24 in the training subset beyond the exact-decimal reference. Matching or nonmatching counts alone do not establish causation; the recovered report description and reconstruction show the earlier 2,295/980 values are complete-row counts.

## Date representation

Every date field in both releases is an ISO calendar date. The updated file has 1,637 unique raw date strings; the historical file has 1,529. There are no timestamps, timezone tags, alternate formats, leading/trailing whitespace, or unparseable dates. Raw, losslessly normalized, and source-local calendar-date comparisons have the same duplicate metrics. Date standardization creates no additional key collisions in these sources. Synthetic tests separately demonstrate how calendar-date conversion could merge a date and a timestamp if such representations were present.

## Reproducibility and deliverables

The audit source verifies source SHA-256 before comparison, writes only aggregate outputs, and does not create any record-level diagnostic file. Run the Python audit on Atlas with the repository Python environment, the two authoritative paths as `--updated-csv` and `--historical-csv`, and an output directory separate from the source directory. The base R script independently cross-checks raw and exact-decimal keys. Focused synthetic tests are in `tests/test_observation_duplicate_precision.py`.

| Artifact | Contents |
| --- | --- |
| `observation_duplicate_precision_summary.csv` | Required per-method metrics, including rows, unique keys, duplicate groups, participating rows, redundant rows, and maximum multiplicity |
| `observation_coordinate_precision_summary.csv` | Aggregate longitude/latitude decimal-place distributions and formatting checks |
| `observation_rounding_sensitivity.csv` | Precision 10 through 2 diagnostic results for both releases and temporal subsets |
| `observation_date_normalization_summary.csv` | Raw, lossless, and calendar-date comparison results |
| `observation_duplicate_audit_manifest.json` | Checksums, parser and method details, date audit, cross-release overlap, definitions, and output inventory |
| `observation_duplicate_precision_r_crosscheck.csv` | Aggregate R cross-check |
| `scripts/observation_duplicate_precision_audit.py` | Python implementation and aggregate report generation |
| `scripts/observation_duplicate_precision_audit.R` | Independent base R exact-key cross-check |

## Validation and limitations

The focused Python synthetic test module contains 12 tests covering exact complete-row duplication, redundant-row versus group counts, trailing-zero equivalence, a differing final retained digit, round-only collisions, date and coordinate key distinctions, release overlap, float64 collapse of distinct exact decimals, date-to-calendar collisions, exponent notation, and invalid decimal rejection. On Atlas, all 12 passed with Python's standard-library `unittest` runner. The Atlas project Python environment did not have pytest installed; no dependency was installed or environment modified. The R cross-check completed on Atlas using the repository R environment wrapper. No package-wide, model, Slurm, or production validation was run.

The audit establishes duplication in the source representation and its exact numerical coordinates. It cannot determine whether repeated records are separate detections, repeated reporting of the same detection, or ingestion artifacts. The source owner has not supplied event identifiers or duplicate semantics. This result does not resolve observation release completeness, historical revision provenance, or artifact lineage.
