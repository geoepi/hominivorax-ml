# Atlas environment

Status: **verified for Task 1 preflight** on 2026-10-02. No production model
fit or production tensor generation was performed.

## Access and checkout

- SSH endpoint: `atlas-login.hpc.msstate.edu` using the established Step SSH
  configuration; the allocated compute host was
  `atlas-devel-1.hpc.msstate.edu`.
- Atlas repository: `/project/disease_ecology/STGNN`.
- Branch: `feature/atlas-preflight-data-contract`.
- Starting commit: `45842f994676cd0a39eb3b98f5f6ed834f89f1ee` (Task 1B
  provenance commit; no merge, rebase, or force-push was used).
- External runtime root: `/project/disease_ecology/STGNN-output`.

## R and spatial stack

The compute-node stack was loaded through `hpc/env_r.sh`:

```text
udunits/2.2.28
proj/9.7.0
zlib-ng/2.2.4
geos/3.14.0
gdal/3.8.5
intel-oneapi-mkl/2023.2.0
openblas/0.3.30
xz/5.6.3
r/4.4.3
```

R was `4.4.3 (2025-02-28)`. Package versions were terra 1.7.78, sf 1.0.21,
data.table 1.16.2, arrow 25.0.1, ggplot2 3.5.1, jsonlite 1.8.8, and digest
0.6.35. The project R library is external to Git at
`/project/disease_ecology/STGNN-r-lib`.

GDAL was 3.8.5. The report records PROJ runtime 9.2.1 and GEOS runtime
3.14.0; `sf`/Terra report their compiled spatial-library versions separately
(GEOS 3.12.1 and PROJ 9.2.1 in the package report). This compile/runtime
difference was observed and retained as a compatibility note. `projinfo
--version` is unsupported by this Atlas build and therefore returned its usage
text; this is a diagnostic limitation, not a failed spatial operation.

The authoritative Atlas R suite passed: **45 tests, 0 failures, 0 warnings,
0 skips**. The R report is
`/project/disease_ecology/STGNN-output/preflight/r_environment.json`.

## Python and GPU stack

The validated environment is external to Git:
`/project/disease_ecology/STGNN-python-venv`. The helper loads
`py-torch/2.10.0`, which supplies CUDA 12.8 and PyTorch 2.10.0. Installed
versions were Python 3.12.14, NumPy 2.5.3, pandas 3.0.6, pyarrow 25.0.1,
scikit-learn 1.9.1, torch-geometric 2.8.0.post1, and
torch-geometric-temporal distribution 0.56.2 (the installed module reports
runtime version 0.54.0). The validated PyG extension wheels were
torch-scatter 2.1.2+pt210cu128 and torch-sparse 0.6.18+pt210cu128.

Atlas GPU partitions inspected included `gpu-v100`, `gpu-a100-mig7`,
`gpu-a100`, and `gpu-l40s`. The final smoke test was submitted to `gpu-a100`
as Slurm job `20838640`; its completion record and output are retained under
`/project/disease_ecology/STGNN-output/logs/slurm/` and in the final manifest.

## Reproducible execution

The approved source paths are set explicitly before running
`scripts/run_cpu_preflight.sh`. The workflow writes only to the external
STGNN output root. It inventories sources read-only, constructs the approved
environmental intersection mask, builds the real node and graph artifacts,
aligns livestock densities by exact cell-overlap area weighting, runs the
observation diagnostic, executes the R suite and Python contract test, and
assembles the manifest.

Runtime output directories are:

```text
/project/disease_ecology/STGNN-output/{manifests,preflight,derived,graph,runs,logs/slurm}
```

No Python environment or source raster/CSV is stored in Git.
