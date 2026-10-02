# Atlas environment

## Validation status

The canonical module and Python environment have not yet been validated from
this session. The configured host name atlas did not resolve over SSH on
2026-10-02, and the local Windows execution environment has neither Rscript
nor Python on PATH. Consequently, no production-readiness claim is made here.

The supplied R stack remains the required starting point:

    module purge
    module load udunits proj geos/3.12.1 gdal/3.8.5 \
      intel-oneapi-mkl/2023.2.0 r/4.4.3

The exact resolved versions must be captured on Atlas from a compute node.

## Execution classes

### Login node

Use only for Git, path and file inventory, text/configuration work, small
metadata checks known to be safe, SLURM submission, and SLURM state inspection.
Do not use the login node to validate spatial-library runtime behavior or GPU
software.

### Interactive CPU development

After the repository is available on Atlas:

    srun \
      --account=disease_ecology \
      --partition=development \
      --nodes=1 \
      --ntasks=16 \
      --pty bash

Then run:

    source hpc/env_r.sh
    Rscript scripts/atlas_r_environment_report.R \
      --output /project/disease_ecology/STGNN-output/preflight/r_environment.json
    Rscript -e "testthat::test_dir('tests/testthat')"

The report must include sessionInfo(), sf::sf_extSoftVersion(), and
terra::gdal(lib = "all"), plus shell-level versions for GDAL, GEOS, PROJ,
UDUNITS, and Intel MKL.

For the complete CPU preflight, set the read-only source paths and the
validated canonical template explicitly, then run:

    export STGNN_OBSERVATIONS=/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv
    export STGNN_ENVIRONMENTAL_ROOT=/project/disease_ecology/cds-datagrab-output/data/production
    export STGNN_LIVESTOCK_ROOT=/project/disease_ecology/animal-data-warehouse/livestock
    export STGNN_TEMPLATE_PATH=/path/to/validated/weekly/template.tif
    export STGNN_TEMPLATE_PRODUCT=validated_product_name
    export STGNN_TEMPLATE_WEEK=YYYY-Www
    export STGNN_PYTHON_ENV=/path/to/validated/python/environment
    source scripts/run_cpu_preflight.sh

The orchestration refuses to guess the canonical template, product, week, or
Python environment. It writes only to STGNN_OUTPUT_ROOT and runs environment
validation, source audits, week/geometry inventory, canonical-template
validation, node/graph construction, observation-to-grid diagnostics, R tests,
and the Parquet contract smoke test.

### CPU batch

Submit hpc/run_cpu_preflight.sbatch only after creating the external output
directories:

    mkdir -p /project/disease_ecology/STGNN-output/{manifests,preflight,derived,graph,runs,logs/slurm}
    sbatch hpc/run_cpu_preflight.sbatch

Record the resulting SLURM job ID in the preflight manifest.

### GPU batch

Do not guess the GPU partition or CUDA compatibility. Inspect Atlas first:

    sinfo
    scontrol show partition
    module spider cuda

Create or activate the validated Python environment only after the available
CUDA toolchain and PyTorch/PyG compatibility are known. Set
STGNN_PYTHON_ENV to that environment, then submit:

    source hpc/env_python.sh
    python python/gconvgru_smoke.py

The helper hpc/submit_gpu_smoke.sh accepts the inspected GPU partition as its
sole argument and requests one GPU. The smoke test must import PyTorch,
confirm CUDA, allocate a GPU tensor, import PyG and GConvGRU, run forward and
backward, and verify finite gradients.

## Known constraints

- Production source paths are external to Git and must remain read-only.
- Runtime artifacts belong under /project/disease_ecology/STGNN-output.
- No Python environment is committed to this repository.
- The GPU partition and exact package versions are intentionally unresolved
  until Atlas is reachable.
- The environment report records LOADEDMODULES/module-list output, shell-level
  GDAL/GEOS/PROJ/UDUNITS checks, MKLROOT, and the required R package versions.
