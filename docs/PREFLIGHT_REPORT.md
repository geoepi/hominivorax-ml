# STGNN Task 1 preflight report

Report status: **blocked pending Atlas access**  
Report date: 2026-10-02  
Requested branch: feature/atlas-preflight-data-contract

This report records what was actually established in the current execution
environment. Atlas-derived quantitative results are explicitly marked pending;
no source observation, environmental raster, or livestock raster was copied or
modified.

## 1. Executive summary

The local repository bootstrap and reproducible preflight scaffolding are
complete. The canonical Atlas checkout and external output root could not be
verified because the configured SSH host atlas returned “Could not resolve
hostname atlas: No such host is known.” The local environment also lacks
Rscript and Python. Therefore the data audit, raster inventory, canonical-grid
selection, graph artifact, R/Python interoperability test, and GPU smoke test
have not been run and must not be represented as successful.

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

Pending compute-node validation. Required evidence remains:
sessionInfo(), sf::sf_extSoftVersion(), terra::gdal(lib = "all"), and
shell-level GDAL, GEOS, PROJ, UDUNITS, and Intel MKL versions. The local
Windows session reported Rscript unavailable.

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

Pending Atlas access. The twelve required products and their weekly-only
directory rule are encoded in scripts/inventory_rasters.R. Counts, endpoints,
missing/duplicate weeks, metadata, valid-cell counts, and exact geometry
comparisons remain unobserved.

## 10. Canonical-grid assessment

Pending. The intended template is one validated weekly environmental raster
whose geometry is common to the products. Selection is based on geometry
consistency only. No canonical product or environmental mask was selected in
this session.

## 11. Observation-to-grid assessment

Pending. No observation coordinates were read. The R implementation is designed
to interpret lon/lat as WGS84, transform to the template CRS, assign valid
cells, and aggregate diagnostic detection counts by node and ISO week. It will
report outside-extent and nodata assignments separately and will not call
unobserved cells biological absences.

## 12. Livestock-data inventory

Pending Atlas access. The five required source filenames are encoded in the
inventory entry point. CRS, dimensions, resolution, extent, nodata, data type,
value range, units metadata, and relationship to the canonical grid are not
yet observed. No definitive resampling or aggregation method was chosen.

## 13. Queen-graph assessment

The deterministic R graph constructor and unit tests are present, but no
production node universe exists until the canonical raster is validated. The
representation is paired directed edges for a fixed binary queen graph with
no self-loops. QA covers symmetry, duplicates, index validity, degree,
isolates, connected components, boundary behavior, and masked-cell handling.

## 14. R/Python interoperability test

Pending because no validated R or Python runtime is available locally and no
Atlas artifacts exist. The contract specifies Parquet node/edge artifacts and
zero-based contiguous node IDs suitable for direct PyG edge_index conversion.

## 15. GConvGRU synthetic GPU smoke test

Pending GPU allocation. The test uses a four-node synthetic directed graph,
allocates inputs and edges on CUDA, runs GConvGRU forward propagation, computes
a differentiable scalar loss, runs backward propagation, and checks finite
gradients. It does not use real environmental or observation tensors.

## 16. Tests performed

The R and Python test suites were added but not executed because the local
environment has neither Rscript nor Python. No test result is claimed. Atlas
execution should run the ordinary R testthat suite separately from the
environment and GPU smoke tests.

## 17. Problems encountered and resolutions

1. Atlas SSH host resolution failed. Resolution: stop Atlas-dependent work and
   record the blocker; do not fabricate inventory results.
2. Rscript and Python are absent locally. Resolution: keep runtime validation
   on Atlas compute nodes as required.
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

The local bootstrap and preflight scaffolding were committed as 9df0ef5
(bootstrap Atlas preflight project structure) on
feature/atlas-preflight-data-contract and pushed to origin. This report update
will be committed separately. The branch must not be merged into main.
