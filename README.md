# STGNN

Spatiotemporal graph neural-network reconnaissance for disease-ecology detection data.

The validated STGNN development history through Task 3E is consolidated on `main`.
Protected Atlas source data and generated model/raster artifacts are not stored in
this repository.

## Current status

Task 3E rasterized the persisted, development-frozen V2-A predictions onto the
canonical environmental grid and produced the documented map figures, manifests,
checksums, and QA report. The outputs are historical pseudo-prospective
reconstructions; they do not constitute an independent prospective evaluation.

`STGNN-Hurdle-V2A` remains a development-frozen candidate awaiting independent
prospective evaluation. No new predictive model was fitted during repository
reconciliation.

## Scope boundary

The repository documents and tests the staged model-development workflow. Future
predictor augmentation is separate from this checkpoint and must not be inferred
from the consolidated V2-A history.

## Repository layout

- R/: reusable date, grid, graph, and observation-audit functions.
- python/: Parquet contract and synthetic GConvGRU smoke tests.
- hpc/: Atlas module and SLURM wrappers.
- scripts/: command-line entry points.
- tests/: unit tests and environment-test guidance.
- docs/: environment, data-contract, model-history, and V2-A documentation.
