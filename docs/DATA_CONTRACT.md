# Data contract

This document defines the Task 1 boundary between Atlas spatial preprocessing
in R and neural-network work in Python. It does not authorize production model
fitting or production tensor generation.

## Immutable sources

- Observations:
  `/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv`
- Weekly environmental root:
  `/project/disease_ecology/cds-datagrab-output/data/production/`, using only
  each product's `weekly/` directory.
- Livestock root:
  `/project/disease_ecology/animal-data-warehouse/livestock/`

The sources remain read-only. Runtime artifacts belong under
`/project/disease_ecology/STGNN-output`.

## Environmental support and canonical template

All 12 required products have 238 weekly rasters covering `2022-W01` through
`2026-W30`, with no missing or duplicate ISO weeks. Their geometry is common:
202 rows by 293 columns, approximately 24.9950 by 24.9437 km cells, and the
same Albers-style projected CRS. The repeated `.tif.json` sidecars were
reported as unexpected directory entries by the inventory; they were not used.

The native ERA5 masks contain 16,759 valid cells and the native ERA5-Land masks
contain 16,756. Masks were identical within each product at the earliest,
middle, and latest common weeks checked (`2022-W01`, `2024-W15`, and
`2026-W30`). The approved canonical support is the cellwise intersection of
all 12 valid masks, without imputation: **16,756 valid cells**, SHA-256
`a5a6bf07c8ffe7198c2d5ed6823871792831d5e1a9210f4b06fdab3fa0840056`.

The geometry template is the real weekly raster:

```text
product: era5_mintemp
week: 2022-W01
file: /project/disease_ecology/cds-datagrab-output/data/production/era5_mintemp/weekly/mintemp_2022-W01.tif
```

Template selection is based on verified common geometry, not ecological
preference. The derived intersection mask is stored separately at
`/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif`.

## Observation period and semantics

The source contains 136,670 rows with columns `date`, `host`, `lon`, and
`lat`. Its SHA-256 is
`099f5fcc61dbd3686bd9bfd0dbfb0a4e37a36f2cba8b443580d2c456544f8a41`.
There are no missing coordinates/dates, malformed coordinates, or date parsing
failures. The valid date range is 2022-02-10 through 2026-07-25; 9,013 records
precede 2024 and 127,657 are on or after 2024-01-01. There are no exact-row
duplicates and one duplicate lon-lat-date record.

The maximum date is 2026-07-25 (`2026-W30`). The latest fully completed ISO
week is `2026-W29`, so the candidate analysis endpoint is **2026-07-19** and
there are **133 target weeks** beginning 2024-01-01. The filename date was not
used.

Observations are transformed from WGS84 lon/lat to the template CRS and mapped
to canonical cells. A zero is **no recorded detection**, not confirmed
biological absence. Aggregation is by node and ISO week using the recorded
detection count.

## Nodes and graph

The node table contains the required `node_id`, `raster_cell`, `row`, `column`,
template-CRS `x,y`, and WGS84 `lon,lat` columns. IDs are deterministic,
zero-based, contiguous, and ordered row-major; only canonical valid cells are
present. The node-to-raster-cell mapping is lossless.

The graph is fixed, binary, undirected queen adjacency on canonical valid
cells, represented as paired directed rows for PyG. The real graph has 16,756
nodes and 128,684 directed edges (64,342 undirected pairs), degree range 0–8,
17 isolated nodes, 31 connected components, no duplicate directed edges, no
invalid indices, no self-loops, and exact symmetry. The observed disconnected
components are recorded rather than repaired.

## Livestock contract

The available goat, cattle, sheep, horse, and pig layers are treated as
continuous animal-density surfaces under the approved Task 1D decision. Their
metadata do not state explicit units, so no unit label is inferred.

The clearly corresponding pig layer was found at
`/project/disease_ecology/animal-data-warehouse/livestock/pig_density20.tif`;
the requested `.tiff` spelling was absent. Feral-swine estimates and non-raster
records were not substituted.

Alignment uses an exact cell-overlap, area-weighted mean density in the common
projected CRS. It uses actual overlap areas, preserves covered mass, reports
partial source coverage, and performs no nearest-neighbor, bilinear, raw-sum,
or extrapolative resampling. Aligned diagnostic rasters and node covariates are
external runtime artifacts only.

## R/Python boundary

R writes `nodes.parquet` and `edges_queen.parquet`; Python reads them with
pandas/pyarrow, verifies schemas and checksums, checks zero-based contiguous
IDs and edge bounds, and converts the paired representation to a two-row
PyTorch Geometric `edge_index`. Python does not reconstruct topology.

The Atlas contract smoke passed with node SHA-256
`804d908021c6469a17b189efd19c34cc4a2307a85d88ae70f596295bce2c8e7f` and edge
SHA-256 `2b2ead33d2bc04b20a724a4af9f92907cc5ef283929b7f3a8282376a53d41c19`.
