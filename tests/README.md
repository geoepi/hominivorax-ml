# Tests

Run ordinary R unit tests on a compute node with the validated R module
environment:

    Rscript -e "testthat::test_dir('tests/testthat')"

The suite covers strict dates, ISO weeks, missing/duplicate raster weeks,
deterministic grid indexing, queen topology, masked-cell topology, and a
synthetic observation-to-grid diagnostic. Synthetic tests use temporary
rasters and never touch protected source paths.

Environment tests are intentionally separate. The CPU geospatial report uses
the module stack in hpc/env_r.sh, and the GPU acceptance test is
python/gconvgru_smoke.py submitted through hpc/submit_gpu_smoke.sh only after
the Atlas GPU partition and Python environment have been verified.
