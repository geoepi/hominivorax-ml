# STGNN Task 1 preflight report

Report status: **blocked pending Atlas access**
Report date: 2026-10-02
Requested branch: feature/atlas-preflight-data-contract

This report records what was actually established in the current execution
environment. Atlas-derived quantitative results are explicitly marked pending;
no source observation, environmental raster, or livestock raster was copied or
modified.

## 1. Executive summary

The local repository bootstrap and reproducible preflight implementation are
complete. The canonical Atlas checkout and external output root could not be
verified because the configured SSH host atlas returned “Could not resolve
hostname atlas: No such host is known.” Python is unavailable and Rscript is
not on PATH, although a bundled local R 4.5.0 runtime is available. Therefore
all Atlas-derived checks remain not attempted;
the new inventory, observation-to-grid, canonical-template validation, CPU
orchestration, and manifest code must not be represented as successful runtime
results.

## 2. Repository/bootstrap status

- Remote: https://github.com/JMHumphreys/STGNN.git
- Initial repository state: one .gitignore file at commit efde3da.
- Local feature branch: feature/atlas-preflight-data-contract.
- Added: protected-data ignore rules, R/, python/, scripts/, hpc/,
  config/, tests/, and required documentation.
- Atlas checkout: not reachable from this session; no second repository was
  created.
- External runtime root: not reachable and not modified.

## 3. SAE execution summary

The required governance file was read before repository changes. Work in this
session is limited to deterministic Level-1 scaffolding and diagnostics.
Scientific choices about estimands, masks, livestock aggregation, validation,
features, and architecture remain unresolved and are not silently decided.

## 4. Atlas execution environment

Pending. No Atlas hostname, node type, SLURM job ID, module resolution, or
external output directory could be observed. The reusable R wrapper contains
the supplied starting module stack but is not labeled production-ready.

## 5. R geospatial environment

Pending Atlas compute-node validation. Required evidence remains:
sessionInfo(), sf::sf_extSoftVersion(), terra::gdal(lib = "all"), and
shell-level GDAL, GEOS, PROJ, UDUNITS, and Intel MKL versions. The local
Windows session used bundled R 4.5.0 only for synthetic checks; it is not the
canonical Atlas R 4.4.3 environment. The local package check found terra
1.8.42, sf 1.0.20, data.table 1.17.0, arrow 20.0.0, and ggplot2 3.5.2; these
versions are not substituted for the required Atlas stack.

## 6. Python/GPU environment

Pending GPU-node validation. No CUDA device, Python version, PyTorch version,
PyG version, PyG Temporal version, or compatible activation path was observed.
The local Windows session reported python unavailable. The synthetic smoke
test is present but was not run.

## 7. Observation-data inventory

Pending Atlas access. The required source path is:

/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv

Checksum, file size, row count, schema, missingness, coordinate bounds,
duplicate counts, date range, ISO-week counts, and post-2024 summaries are
therefore unavailable. The read-only audit entry point is
scripts/audit_observations.R.

## 8. Candidate analysis period

Pending observation audit. The implemented rule uses the maximum valid parsed
observation date and selects its Sunday if that date is Sunday; otherwise it
selects the preceding Sunday. This produces a candidate complete-week endpoint
without using the date embedded in the filename. Environmental availability
must be compared after inventory and must not be silently truncated.

## 9. Environmental weekly-data inventory

Not attempted on Atlas. scripts/inventory_rasters.R now records parsed ISO
year/week, missing and duplicate weeks, unexpected filenames, metadata-only
headers, common coverage, and exact geometry comparisons without reading every
weekly raster cell.

## 10. Canonical-grid assessment

Not attempted. The intended template is one validated weekly environmental
raster whose geometry is common to the products. Selection is based on
geometry consistency only. scripts/validate_canonical_template.R now refuses a
template that does not exactly match the inventory reference; no canonical
product or environmental mask was selected in this session.

## 11. Observation-to-grid assessment

Not attempted. scripts/observation_to_grid.R now interprets lon/lat as WGS84,
transforms to the template CRS, assigns valid cells, aggregates detection
counts by node and ISO week, and writes a summary plus Parquet node-week
diagnostic. It reports outside-extent, masked/nodata, and invalid-coordinate
records separately and does not call unobserved cells biological absences.

## 12. Livestock-data inventory

Not attempted on Atlas. The five required source filenames are encoded in the
inventory entry point. Metadata, descriptive tags, and static-layer min/max
checks are collected when available; units and count/density semantics remain
unresolved unless explicitly stated by the raster metadata. No definitive
resampling or aggregation method was chosen.

## 13. Queen-graph assessment

Implementation verified by inspection only; no Atlas node universe exists
until the canonical raster is validated. The representation is paired
directed edges for a fixed binary queen graph with no self-loops. QA covers
symmetry, duplicates, index validity, degree, isolates, connected components,
boundary behavior, and masked-cell handling. The masked-cell test now compares
expected raster-cell adjacency rather than compact node IDs.

## 14. R/Python interoperability test

Not attempted because no validated R or Python runtime is available locally and
no Atlas artifacts exist. The CPU orchestration now writes nodes.parquet and
edges_queen.parquet, runs the Python contract check, and records artifact
checksums in the final manifest.

## 15. GConvGRU synthetic GPU smoke test

Not attempted because no GPU allocation was available. The test uses a
four-node synthetic directed graph, allocates inputs and edges on CUDA, runs
GConvGRU forward propagation, computes a differentiable scalar loss, runs
backward propagation, checks finite gradients, and records package versions and
GConvGRU source/signature inspection. It does not use real data.

## 16. Tests performed

The R unit suite passed locally with 39 tests using bundled R 4.5.0. Synthetic
inventory and observation-to-grid CLI checks also passed, including JSON and
Parquet output validation. These are not Atlas environment results. Python
contract and GPU tests were not executed because Python is unavailable. The
Atlas sequence is available in scripts/run_cpu_preflight.sh; GPU validation
remains a separate SLURM smoke test.

## 17. Problems encountered and resolutions

1. Atlas SSH host resolution failed. Resolution: stop Atlas-dependent work and
   record the blocker; do not fabricate inventory results.
2. Python is absent locally and Rscript is not on PATH. Resolution: use the
   bundled R 4.5.0 only for synthetic/unit checks and keep canonical runtime
   validation on Atlas compute nodes as required.
3. The checkout Git metadata initially required an explicit permission to
   create the requested branch. The feature branch was then created; no merge
   or history rewrite was performed.

## 18. Unresolved scientific/modeling decisions

No decision was made about true absence versus no recorded detection, livestock
units or aggregation, environmental feature elimination, mask reconciliation,
temporal/spatial validation folds, hurdle likelihood, or graph alternatives.
These remain for later review under the stated governance rules.

## 19. Recommended inputs for Task 2

First complete the Atlas preflight with recorded module/package versions,
source checksums, weekly inventories, geometry comparison, observation-to-grid
diagnostics, livestock metadata review, Parquet invariants, and GPU smoke-test
output. Only then revisit unresolved scientific decisions and design the
production preprocessing contract.

## 20. Git status and commit history

The prior branch head b47730c was reconciled before Task 1B changes. The
implementation is committed as 79665b3 (complete Task 1B preflight
diagnostics). This documentation update will be committed separately. The
branch must not be merged into main.
