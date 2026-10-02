# Data contract

This document defines the Task 1 boundary between spatial preprocessing in R
and neural-network work in Python. It does not authorize production fitting.

## Immutable sources

- Observations:
  /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv
- Weekly environmental root:
  /project/disease_ecology/cds-datagrab-output/data/production/
  using only product weekly/ subdirectories.
- Static livestock root:
  /project/disease_ecology/animal-data-warehouse/livestock/

These sources are read-only. They must not be copied into Git, rewritten, or
relocated. Runtime outputs belong under
/project/disease_ecology/STGNN-output.

## Canonical grid and node indexing

The canonical template is one validated weekly environmental raster selected
by exact geometry consistency, not ecological preference. The node universe is
every non-nodata cell in that template.

Node IDs are deterministic, zero-based, and ordered row-major by raster row and
then column. raster_cell remains the one-based row-major raster cell index.
The required node table columns are:

| column | meaning |
| --- | --- |
| node_id | zero-based stable model-node index |
| raster_cell | one-based raster cell index |
| row | one-based raster row |
| column | one-based raster column |
| x, y | template-CRS cell center |
| lon, lat | WGS84 cell center |

The mapping is lossless: node_id -> raster_cell -> row/column and coordinates.
Valid environmental cells are retained even when no detection is recorded.

## Time indexing and preliminary target definition

Dates are parsed strictly as ISO calendar dates. Weeks use ISO Monday-Sunday
identifiers. The formal target period begins 2024-01-01. The candidate endpoint
is the Sunday of the latest complete ISO week supported by the maximum valid
observation date; it must then be compared with environmental availability.

For Task 1, a zero count means no recorded detection in the diagnostic
aggregation. It is not interpreted as confirmed biological absence. The
modeling estimand remains detection/non-detection pending later evidence.

## Queen graph

The preliminary graph is fixed, binary, undirected queen contiguity on valid
canonical-template cells. The R edge artifact stores paired directed rows so
that it can be consumed directly as a PyG edge_index:

    source_node,target_node

There are no self-loops unless a later verified GConvGRU implementation
requires them. No distance, direction, host, environmental-similarity, or
learned weighting is part of this contract.

## Parquet boundary

R writes:

- node table: one row per valid template cell with the node columns above;
- edge table: two integer columns, source_node and target_node.

Python reads these artifacts with pandas/pyarrow, verifies schemas, checks that
node IDs are contiguous and that edge indices are in range, then constructs a
two-row PyTorch Geometric edge_index tensor. Python must not rederive spatial
geometry or graph topology.

The contract smoke test also records SHA-256 checksums and shape/dtype
invariants. Production tensorization and model fitting are outside this phase.
