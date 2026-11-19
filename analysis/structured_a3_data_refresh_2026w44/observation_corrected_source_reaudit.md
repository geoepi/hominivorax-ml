# Corrected observation source re-audit

Audit date: 2026-11-19
Previous audit commit: `b39e44ba5da5dd6dea5c0c26072d68b66e2797ba`

## I. Governance and repository state

This read-only re-audit ran on the existing `analysis/structured-a3-2026w44-refresh` branch. The approved WSL/Ubuntu `atlas-ssh` wrapper was used for Atlas access. The Python audit reused the committed exact-decimal/key-count helpers; the independent base R script was reused with an optional expected-checksum argument for the corrected source.

Observation rows and coordinates remained on Atlas. No observation source, model input, model artifact, production pointer, or shared software environment was modified. No model fitting or production qualification was run.

## II. Corrected source identity and checksum

| Field | Corrected source |
| --- | --- |
| Path | `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2026-11-13.csv` |
| SHA-256 | `2f9cf04ffe01712b8e5498d809f542d159ff1cb33ae8b567aa6644e9c4f05de5` |
| File size | 7,302,057 bytes |
| Modification time | 2026-11-19 09:00:58.511573930 -0600 |
| Rows | 167,030 |
| Columns | `date, host, lon, lat` |
| Earliest / latest observation date | 2022-02-10 / 2026-11-13 |
| Latest observed ISO week | 2026-W46 |

The checksum was the same immediately before and after the audit. The previous source checksum was `8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc`. That checksum was not found among the observation snapshots in the authorized `case_detections` directory; the matching filename now has the corrected checksum. No immutable copy of the previous source version was available for key-level comparison.

## III. Source integrity

The corrected file retains the expected four-column schema and order. The audit found zero blank fields, invalid calendar dates, date whitespace, date-time values, non-ISO date text, invalid or nonfinite coordinates, or out-of-range coordinates. All 167,030 rows have valid longitude and latitude values.

The raw parser retained the CSV fields as strings. Pandas default inference returned strings for `date` and `host`, and float64 for `lon` and `lat`. No field or type-definition change was identified. Date values remain ISO calendar dates with 1,637 unique dates.

Longitude precision remains 0–8 decimal places and latitude 0–14. There is no scientific notation, trailing fractional zero, alternate text form for equal decimal values, or float64 collision. Exact-decimal and float64 key results agree. The distribution of coordinate decimal-place record totals changed in five bins between source versions, so the rounding sensitivity diagnostic was rerun for the corrected source. It remains diagnostic only; rounded coordinates are not used for the key audit or as source data.

## IV. Exact observation-key uniqueness

The authoritative key remains source-local calendar date plus exact numerical decimal longitude and latitude; host is excluded. Duplicate groups, participating rows, and redundant rows use the definitions in the previous audit: a group contributes 1, its participating rows contribute multiplicity `k`, and redundant rows contribute `k-1`.

| Corrected-source temporal subset | Rows | Unique exact-decimal keys | Duplicate groups | Rows in groups | Redundant rows | Max multiplicity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Entire source | 167,030 | 164,767 | 2,263 | 4,526 | 2,263 | 2 |
| Before 2025-W01 | 44,907 | 44,907 | 0 | 0 | 0 | 1 |
| Original W16 horizon, 2025-W01–2026-W16 | 91,980 | 91,005 | 975 | 1,950 | 975 | 2 |
| Extended W44 horizon, 2025-W01–2026-W44 | 121,155 | 118,892 | 2,263 | 4,526 | 2,263 | 2 |
| After 2026-W16 | 30,143 | 28,855 | 1,288 | 2,576 | 1,288 | 2 |
| After 2026-W44 | 968 | 968 | 0 | 0 | 0 | 1 |

The corrected file therefore **does not satisfy the zero-duplicate-key acceptance criterion**. It currently contains 2,263 duplicate observation-key groups.

## V. Complete-record and conflicting-host duplicates

| Temporal subset | Complete-record duplicate groups | Key groups with conflicting host attributes |
| --- | ---: | ---: |
| Entire source | 2,248 | 15 |
| Before 2025-W01 | 0 | 0 |
| Original W16 horizon | 967 | 8 |
| Extended W44 horizon | 2,248 | 15 |
| After 2026-W16 | 1,281 | 7 |
| After 2026-W44 | 0 | 0 |

All current duplicate groups have multiplicity two. The 15 host-conflicting groups are coordinate-key duplicates whose repeated rows differ in host. Host is not part of the observation-key contract.

## VI. Python and R audit agreement

Python compared complete raw records, raw character keys, exact-decimal keys, and float64 keys using the existing audit helpers. The R implementation independently checked the raw-record, raw-key, and exact-decimal results after reading all fields as character. All **24** comparable aggregate rows matched with no discrepancies.

The exact-decimal key is authoritative. Raw character, exact-decimal, and float64 key metrics agree for this source. No coordinate rounding, truncation, spatial transformation, grid assignment, or weekly aggregation was used in duplicate detection.

The coordinate precision distribution changed in five decimal-place bins between the prior and corrected snapshots, so the existing rounding sensitivity diagnostic was rerun. These are duplicate-key groups after deliberate rounding; they are not source-precision counts.

| Coordinate decimal places | Entire-source duplicate groups | Entire-source redundant rows | W16 duplicate groups | W16 redundant rows |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 2,336 | 2,336 | 999 | 999 |
| 9 | 2,336 | 2,336 | 999 | 999 |
| 8 | 3,408 | 3,408 | 1,463 | 1,463 |
| 7 | 3,901 | 3,933 | 1,611 | 1,619 |
| 6 | 4,429 | 4,789 | 1,868 | 2,031 |
| 5 | 4,625 | 4,995 | 2,045 | 2,220 |
| 4 | 4,944 | 5,426 | 2,256 | 2,472 |
| 3 | 6,745 | 7,380 | 3,803 | 4,124 |
| 2 | 10,744 | 12,103 | 6,679 | 7,406 |

No tested rounding precision reproduces the previous 2,295 overall or 980 W16 counts. The full aggregate diagnostic, including unique keys and participating rows, is in `observation_corrected_rounding_sensitivity.csv`.

## VII. Previous versus corrected source comparison

| Scope with retained prior aggregate | Previous rows | Corrected rows | Row delta | Previous unique keys | Corrected unique keys | Previous duplicate groups | Corrected duplicate groups | Previous / current conflicting-host groups |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Entire source | 167,078 | 167,030 | -48 | 164,767 | 164,767 | 2,311 | 2,263 | 16 / 15 |
| Before 2025-W01 | 44,907 | 44,907 | 0 | 44,907 | 44,907 | 0 | 0 | 0 / 0 |
| Original W16 horizon | 91,993 | 91,980 | -13 | 91,005 | 91,005 | 988 | 975 | 8 / 8 |
| After 2026-W16 | 30,178 | 30,143 | -35 | 28,855 | 28,855 | 1,323 | 1,288 | 8 / 7 |

These are aggregate comparisons against the previous audit outputs. The unchanged unique-key totals do not establish that the same keys were retained. Because the old source file is unavailable, retained, removed, and added key identities; changed multiplicities; host changes for retained keys; and week-by-week changes from the previous source cannot be calculated. The aggregate deltas are consistent with 48 fewer redundant rows overall, but do not establish that precisely 48 prior groups were resolved without other changes.

The previous aggregate baseline has no W44-extended or post-W44 subset results. The corrected counts for those scopes are available in the summary CSV, but cannot be compared to the previous source at those horizons.

**The re-audit cannot conclude that all 2,311 previously reported groups were resolved.** The corrected source still has 2,263 groups, and the absent previous file prevents identifying which groups persisted or changed.

## VIII. Historical W16 observation comparison

The historical source remains `combined_clean_obs_2027-07-31.csv`, SHA-256 `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e`, with 136,714 rows. Its content ends at 2026-07-31 (2026-W31).

Audited separately within that historical file, there are four exact-decimal observation-key groups overall (11 participating rows, seven redundant rows, maximum multiplicity four), including zero groups in the original W16 training horizon. These within-file duplicates are distinct from the cross-release overlap shown below.

| Comparison subset | Corrected rows | Historical rows | Shared unique keys | Corrected-only keys | Historical-only keys | Complete-record overlap | Shared keys with different host sets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Entire releases | 167,030 | 136,714 | 82,180 | 82,587 | 54,527 | 31,036 | 51,144 |
| Original W16 horizon | 91,980 | 79,257 | 53,641 | 37,364 | 25,616 | 15,988 | 37,653 |
| Extended W44 horizon | 121,155 | 91,806 | 65,471 | 53,421 | 26,329 | 15,988 | 49,483 |

The weekly comparison output reports current-versus-historical row and key totals by ISO week. The historical release has no rows after W31, so corrected-source observations in W42–W46 have no historical-week counterparts. These are cross-release differences, not within-source duplicates. The corrected file is a replacement snapshot, not an append operation. Historical revisions remain substantial; no release notes or provenance in the inspected source directory explain them.

## IX. Weekly observation availability through W44

The corrected weekly inventory covers 249 consecutive ISO weeks from 2022-W06 through 2026-W46. The selected recent weeks are:

| ISO week | Observations | Unique exact keys | Duplicate groups |
| --- | ---: | ---: | ---: |
| 2026-W42 | 1,004 | 994 | 10 |
| 2026-W43 | 1,021 | 1,021 | 0 |
| 2026-W44 | 911 | 911 | 0 |
| 2026-W45 | 668 | 668 | 0 |
| 2026-W46 | 300 | 300 | 0 |

The latest observation date is 2026-11-13 (W46). The candidate endpoint remains 2026-W44, October 26–November 1. The inspected `case_detections` directory contains only its 61-byte README pointer and source files; no release-specific complete-week declaration was found. The 911 W44 observations and subsequent W45/W46 observations do **not** prove W44 completeness.

## X. Tests and deliverables

All 12 existing focused synthetic tests passed on Atlas using the project Python environment and standard-library `unittest`; the re-audit runner compiled successfully. The R cross-check used R 4.4.3 through `hpc/env_r.sh`; Python used 3.12.14 and pandas 3.0.6. No dependencies were installed.

The corrected-source runner is audit version `1.0.1`; the aggregate JSON and CSV outputs parsed successfully. Weekly totals reconcile to 167,030 corrected rows and 136,714 historical rows; duplicate metrics reconcile; all 24 Python/R rows match; the rounding sensitivity diagnostic was rerun because five coordinate precision distribution bins changed; and the corrected source checksum was unchanged during inspection. No model artifacts, input bundles, or production pointers were modified.

The manifest records source hashes, execution environment, integrity checks, previous aggregate comparison, R agreement, test result, decisions, and blockers. The coordinate precision report, historical release comparisons, weekly outputs, and summary outputs contain aggregate counts only.

## XI. Remaining refresh blockers

The corrected source has no new schema, missingness, date-validity, or coordinate-validity problem, but duplicate exact-decimal observation keys remain. The original W44 training scope therefore fails the observation-key uniqueness requirement.

Reporting completeness through W44 remains undocumented. Historical observation revisions relative to the frozen W16 source remain substantial and unexplained. The W29 artifact-lineage question remains a separate outstanding issue. A successful duplicate correction alone would not resolve these input-readiness blockers.

## XII. Repository and pull-request status

This re-audit is being added to the existing `analysis/structured-a3-2026w44-refresh` branch and draft PR #31. The earlier duplicate audit, its source hash, outputs, and decisions are retained as historical evidence. The previous source snapshot was not reconstructed from aggregate counts.

## XIII. Final decision

**Corrected-source decision: `OBSERVATION_DUPLICATES_REMAIN`.** The current corrected CSV contains 2,263 duplicate exact-decimal `(date, lon, lat)` groups.

**Overall readiness: `REFRESH_BLOCKED_BY_INPUT_DATA`.** The corrected source is not suitable for the proposed W44 refresh under the current uniqueness requirement, reporting completeness remains unestablished, and historical revision provenance remains unresolved. Model fitting must not begin.
