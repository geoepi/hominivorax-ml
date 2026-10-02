# STGNN

Spatiotemporal graph neural-network reconnaissance for disease-ecology detection data.

This branch implements the Task 1 preflight scaffolding: Atlas environment wrappers, source-data audit utilities, canonical-grid and queen-graph helpers, and the R-to-Python data-contract smoke tests. Protected Atlas source data are not stored in this repository.

## Current status

The local repository bootstrap is complete. Atlas-derived inventory and runtime results remain pending because the current execution environment cannot resolve the configured atlas SSH host. See docs/PREFLIGHT_REPORT.md for the evidence and the precise stop condition.

## Scope boundary

Task 1 does not fit production models, construct full tensors, tune hyperparameters, generate predictions, or make unresolved scientific decisions. The intended next step after Atlas access is to run the preflight wrappers and replace the pending fields in the report and manifest with observed values.

## Repository layout

- R/: reusable date, grid, graph, and observation-audit functions.
- python/: Parquet contract and synthetic GConvGRU smoke tests.
- hpc/: Atlas module and SLURM wrappers.
- scripts/: command-line entry points.
- tests/: unit tests and environment-test guidance.
- docs/: environment, data-contract, and preflight documentation.
