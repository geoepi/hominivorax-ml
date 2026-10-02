# STGNN Task 1 preflight report

Report status: **completed for Task 1; Task 2 not started**
Report date: 2026-10-02
Branch: `feature/atlas-preflight-data-contract`

## Executive result

Atlas execution established the canonical R environment, source inventories,
candidate analysis period, approved environmental intersection mask, real node
table, real queen graph, livestock-density alignment, observation diagnostics,
R/Python Parquet interoperability, Python/GPU environment, and provenance
manifest. Source observations and rasters were not modified. No production
tensors or model fitting were performed.

## Status classification

| Item | Status | Evidence |
| --- | --- | --- |
| Atlas connectivity and branch | verified | `atlas-devel-1.hpc.msstate.edu`; starting SHA `45842f994676cd0a39eb3b98f5f6ed834f89f1ee` |
| R 4.4.3 spatial environment | verified | `preflight/r_environment.json` |
| R unit/synthetic suite | verified | 45 passed, 0 failed/warned/skipped |
| Observation audit | verified | `preflight/observation_audit.json` |
| Environmental coverage/geometry | verified | `preflight/raster_inventory.json` |
| Canonical support mask | verified | 16,756 cells; intersection SHA recorded below |
| Livestock source semantics | verified by approved Task 1D decision | Continuous density surfaces; units absent from metadata |
| Production resampling/tensorization | not applicable | Explicitly outside Task 1 |
| Real nodes and queen graph | verified | Parquet artifacts and `graph_qa.json` |
| Observation-to-grid diagnostics | verified | `observation_to_grid.json` and node-week Parquet |
| Python contract smoke | verified | 16,756 nodes; 128,684 directed edges; undirected true |
| GPU GConvGRU smoke | verified | Slurm job `20838640`; final smoke output |
| Source-data mutation | verified absent | Source checksum and Git staging checks |
| New scientific decisions | unresolved/not applicable | Task 1D approved mask, density, and pig-search decisions were followed; later architecture/validation decisions remain outside Task 1 |

## Atlas environment

The R run used `atlas-devel-1.hpc.msstate.edu`, R 4.4.3, terra 1.7.78, sf
1.0.21, data.table 1.16.2, arrow 25.0.1, ggplot2 3.5.1, jsonlite 1.8.8,
and digest 0.6.35. The loaded module stack, GDAL/GEOS/PROJ/UDUNITS/MKL
reports, and session information are in `r_environment.json`. A nonfatal
Atlas limitation is that `projinfo --version` prints usage because that build
does not support the option. The report also retains the compile/runtime GEOS
compatibility note.

The Python environment is `/project/disease_ecology/STGNN-python-venv`, with
Python 3.12.14, PyTorch 2.10.0, CUDA runtime 12.8, torch-geometric 2.8.0.post1,
and torch-geometric-temporal distribution 0.56.2/runtime module report 0.54.0.
The environment is external to Git.

## Observation audit and period

The observation source has SHA-256
`099f5fcc61dbd3686bd9bfd0dbfb0a4e37a36f2cba8b443580d2c456544f8a41`, size
5,191,318 bytes, and 136,670 rows. Missing lon/lat/date counts, invalid
coordinates, and date parse failures are all zero. The valid date range is
2022-02-10 to 2026-07-25; 9,013 records precede 2024 and 127,657 are
post-2024. Exact-row duplicates are zero; duplicate lon-lat-date records: one.

The maximum observation date is 2026-07-25 (`2026-W30`); the latest fully
completed ISO week is `2026-W29`; candidate `analysis_end` is **2026-07-19**;
the target contains **133 weeks**.

## Environmental inventory and canonical mask

Each of the 12 required products has 238 files spanning `2022-W01` to
`2026-W30`, with zero missing and zero duplicate weeks. All products support
the candidate endpoint. Geometry is common at 202 x 293 cells with about
24.9950 x 24.9437 km resolution. Representative ERA5 masks have 16,759 valid
cells, while ERA5-Land masks have 16,756. The difference is retained in the
inventory; it was not silently reconciled by choosing one family.

Masks were checked at `2022-W01`, `2024-W15`, and `2026-W30` and were invariant
within every product. The approved cellwise intersection across all 12
predictors has **16,756 valid cells**, SHA-256
`a5a6bf07c8ffe7198c2d5ed6823871792831d5e1a9210f4b06fdab3fa0840056`, and no
imputation. The selected real template is
`era5_mintemp/weekly/mintemp_2022-W01.tif`.

## Livestock alignment

Goat, cattle, sheep, horse, and pig density layers were aligned to the
canonical grid using exact overlap-area-weighted mean density. The source
metadata contain no explicit units. The exact pig layer found by the bounded
search is `livestock/pig_density20.tif`; the requested `.tiff` filename was
not present, and feral-swine estimates were not used.

All five aligned layers preserve covered mass to numerical tolerance. The
canonical destination cell area is approximately 623.4672 square CRS units.
Partial-coverage cell counts were goat 1,156, cattle 1,156, sheep 1,156,
horse 1,302, and pig 1,341. The detailed coverage, ranges, metadata, and
checks are in `preflight/livestock_alignment.json`.

## Real nodes and queen graph

The node table has **16,756** deterministic zero-based row-major nodes and is
lossless back to raster cells and coordinates. The graph has **128,684 directed
edges** (**64,342 undirected pairs**), degree minimum 0, maximum 8, **17
isolated nodes**, and **31 connected components**. Component sizes begin
`16,385, 172, 121, 15, 13, 8, 8, 4, 3, 2`; all remaining components are size
two or one. Duplicates, invalid indices, and self-loops are zero; symmetry is
true. Disconnected components were reported rather than altered.

## Observation-to-grid diagnostics

Of 127,657 post-2024 records, 121,903 were assigned to canonical cells; 5,754
fell on masked/nodata cells, and zero were outside the template extent or had
invalid coordinates. Across 2,228,548 possible node-weeks, 34,129 were
positive and 2,194,419 had no recorded detection (zero fraction 0.9847).
There were 2,197 occupied nodes. Positive detection-count mean was 3.5544,
median 2, variance 15.9207, maximum 72; quantiles at 0, .25, .50, .75, .90,
.95, and 1 were 1, 1, 2, 4, 8, 11, and 72. The fraction of positive
node-weeks with count one was 0.3452. Weekly totals and positive-node counts
are retained in the diagnostic JSON. These zeros mean no recorded detection,
not biological absence.

## R/Python contract and GPU smoke

The contract smoke passed using the R-generated topology. Node Parquet SHA-256
is `804d908021c6469a17b189efd19c34cc4a2307a85d88ae70f596295bce2c8e7f`; edge
Parquet SHA-256 is
`2b2ead33d2bc04b20a724a4af9f92907cc5ef283929b7f3a8282376a53d41c19`. PyG
`edge_index` shape is 2 x 128,684, dtype `torch.int64`, and undirectedness is
true.

GPU job `20838640` ran on `gpu-a100`. Its required acceptance
criteria—CUDA availability, GPU tensor allocation, GConvGRU import, forward,
backward, and finite gradients—are recorded in the smoke output and manifest.

## Provenance and unresolved items

The machine-readable manifest is
`/project/disease_ecology/STGNN-output/manifests/preflight_manifest.json`.
It includes Git identity, Atlas host/job IDs, source paths/checksum, R/Python
environment, inventory, mask, livestock alignment, graph, node-week
diagnostics, Parquet checksums, and test results.

The following remain unresolved for later governed work: the biological
interpretation of non-detection, final feature inclusion/exclusion, temporal
and spatial validation design, statistical likelihood/model architecture, and
any production tensorization. They were not decided autonomously in Task 1.
