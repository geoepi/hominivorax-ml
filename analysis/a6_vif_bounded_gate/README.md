# A6-VIF bounded GPBoost qualification gate

A6-VIF is one isolated, one-shot challenger for the A6 fold 3 / seed 31415
model unit. It preserves the Bernoulli-logit occurrence likelihood, frozen A3
logit offset, all 34 predictors, and the joint Matérn space-time process on
`[week_offset, x_km, y_km]`. GPBoost 1.8.0 uses the prescribed
`full_scale_vecchia` VIF approximation with 200 requested `kmeans++` inducing
points, eight local Vecchia neighbors, time ordering, iterative matrix
inversion, and an explicit 40-neighbor prediction setting.

## Fold and fitting contract

The canonical A6 fold assignment is verified before fitting: outer training
weeks 0–51 and outer validation weeks 52–59. Inner round selection trains on
weeks 0–40 and monitors weeks 41–51. The outer validation labels are not used
for training, covariance estimation, or round selection.

Stage A estimates VIF covariance parameters separately for the inner-training
and complete outer-training partitions. Each estimate uses a deterministic,
spatially stratified sample of 2,048 sites spanning only the applicable
training weeks, with the frozen A3 offset and Bernoulli-logit likelihood.
Stage B initializes in the named order `GP_var`, `GP_range_time`,
`GP_range_space`, sets `train_gp_model_cov_pars=False`, verifies the covariance
values remain unchanged, and retains latent-effect fitting. The inner model
selects rounds with the existing A6 patience; the final model uses all outer
training rows and the selected round count.

The runner exposes only `--mode gate`, fold 3, and seed 31415. A one-shot
execution marker blocks reruns. The job is never automatically resubmitted.
Stage A estimates and model artifacts are written atomically under the unique
run directory on `/90daydata/disease_ecology/`; the original A6 and A6-OPT
locations are read-only inputs.

## Runtime protection and diagnostics

The single Slurm allocation is 16 CPUs, 64 GB, and six hours (96 CPU-hours).
The Python runner enforces an internal 5:20 deadline. Slurm sends `USR1` 30
minutes before the wall limit. A supervisor imposes a hard stop at 5:35 to
leave time for status and checksum finalization. Boosting callbacks record
iterations and available mode/CG diagnostics; covariance optimization tracing
is enabled. Warnings and progress are flushed to durable logs. A native call
that does not return cannot be guaranteed to stop gracefully: the outer
supervisor terminates it and marks any running Stage B attempt incomplete
while preserving completed Stage A estimates.

The complete model-unit runtime used for the speedup includes both Stage A
covariance estimates, Stage B round selection, final fitting, prediction, and
serialization. The report separately records total execution wall time, CPU
hours, process peak RSS, and average use of the 16-CPU allocation. The runtime
and CPU budgets cover data preparation and final qualification as well.

## Qualification

On successful completion, the gate compares predictive skill and calibration
with frozen A3 and the matched original A6 fold 3 / seed 31415 artifact. It
records spatial Moran diagnostics, same-cell temporal residual correlations,
frontier-region metrics, prediction repeatability, leakage checks, covariance
diagnostics, and checksums. The existing A6-OPT predictive and spatial
guardrails apply unchanged. At least 2× comparable wall-clock improvement is
required for `A6_VIF_GATE_SUPPORTED`; a completed but slower scientifically
acceptable fit is `A6_VIF_GATE_SUPPORTED_WITH_LIMITATIONS` and does not
authorize a larger run.

The installed Python API exposes latent-mode iteration counts but no
Python-level convergence boolean. The gate records the available counts and
warnings and labels covariance-optimizer convergence as an iteration-limit
proxy rather than claiming an unavailable native status.

There is no CLI mode or launcher for additional folds, seeds, temporal arrays,
or spatial-stress fitting in this package. No larger experiment is authorized
by a supported gate result.
