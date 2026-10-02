# Tests

Run ordinary R unit tests on a compute node with the validated R module
environment:

    Rscript -e "testthat::test_dir('tests/testthat')"

Environment tests are intentionally separate. The CPU geospatial report uses
the module stack in hpc/env_r.sh, and the GPU acceptance test is
python/gconvgru_smoke.py submitted through hpc/submit_gpu_smoke.sh only after
the Atlas GPU partition and Python environment have been verified.
