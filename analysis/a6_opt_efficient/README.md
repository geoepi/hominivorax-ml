# A6-OPT Efficient Spatiotemporal GPBoost

A6-OPT is a separate experimental challenger based on the frozen A6 specification.
It changes the GPBoost training-neighbor count from 20 to 8 and estimates the
Matérn space-time covariance once for each compatible training partition before
boosting with covariance estimation disabled. Prediction retains the explicit
40-neighbor setting. Frozen A3/A4-S artifacts and the original A6 source and
outputs remain unchanged.

## Two-stage fitting

For each temporal fold, the runner estimates one covariance model on the inner
training partition for seed-specific boosting-round selection, and one on the
complete outer training partition for final fits. Each estimate is reused for
all three boosting seeds. The inner covariance fit sees no inner-monitor
observations; neither covariance fit sees outer validation or future outcomes.
Stage A uses the frozen A3 logit offset and the Bernoulli-logit Matérn
space-time GP. Stage B uses the full training rows, all 34 A3 predictors, the
same offset, and GPBoost's fixed covariance initialization API while retaining
GP random-effect modes and prediction.

Covariance optimization on all rows is not repeated within every boosting
iteration. The original A6 fold 3 / seed 31415 artifact records 45,906 seconds
for inner selection plus final fitting, with a 20-neighbor Vecchia GP. To bound
the standalone Stage A cost, covariance estimation uses 2,048 deterministic,
spatially stratified nodes per partition across every applicable training
week. Sampling uses a fixed 32 by 32 spatial grid and a fixed seed, is
independent of outcomes, includes the domain edges, and records class balance,
temporal coverage, and spatial nearest-neighbor distances. Stage B always uses
all training observations. This subset choice is part of the A6-OPT method and
is reported with each estimate.

The qualification gate is fold 3 / seed 31415, matched to an existing completed
original A6 artifact. It requires a valid covariance fit, fixed Stage B
parameters, correct A3 offsets, repeatable label-free predictions, spatial
diagnostics, and at least a two-fold measured runtime reduction. The report
compares the gate to frozen A3 and the matched original A6 predictions. A
successful gate permits the four-fold temporal evaluation; it does not
automatically submit it. Spatial-stress evaluation is separate and is only
authorized after primary temporal guardrails pass.

## Execution and storage

Use `hpc/submit_a6_opt_gate.sh` for the one-fold gate. If it passes, set
`A6_OPT_GATE_OUTPUT_ROOT` to the completed gate run and use
`hpc/submit_a6_opt_temporal.sh` for the four-fold, three-seed array and its
aggregation dependency. The launcher rejects missing or unsupported gate
decisions. The array is intentionally limited to one fold at a time. Each fold has an independent lock, covariance
estimates, seed attempts, checksums, and completion status. A rerun reuses
validated covariance and completed seed artifacts; failed attempts receive a
new attempt directory.

If the Stage B completion marker exists but the gate comparison stopped on a
recoverable comparison error, run
`A6_OPT_OUTPUT_ROOT=<existing-gate-run> bash hpc/submit_a6_opt_gate_compare.sh`.
This mode requires the original environment manifest and checksum-valid fit
artifacts. It reuses the saved prediction archive without training and records
the model-fit and comparison code revisions separately.

After the primary temporal aggregation reports `primary_guardrails_passed: true`,
set `A6_OPT_OUTPUT_ROOT` to that run root and execute
`hpc/submit_a6_opt_spatial_stress.sh`. The launcher checks the primary decision
before submitting the existing spatial partition one fold at a time, followed
by a separate aggregation job. Spatial-stress results are secondary and do not
alter the primary decision.

Model files, GPBoost training products, prediction arrays, temporary data, and
logs belong under `/90daydata/disease_ecology/hominivorax-ml/a6_opt_efficient/`.
Compact metrics, covariance summaries, provenance, qualification reports,
figures, and checksums belong in `results/`. No A6-OPT model is promoted to
production.
