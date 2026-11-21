# W44 Q1 retrospective execution

This workstream applies the approved 26-origin, three-horizon retrospective
design using origin-specific expanding-window fits under the frozen A3
specification. `E0_LAST_AVAILABLE` (T−1) remains primary; `E1_TRAILING3_MEAN`
(T−1 through T−3) is the sensitivity. The target-week realized environmental
variant is retained only as the existing P5A reference comparison.

## Atlas execution

Run these wrappers from the isolated Atlas worktree:

1. `sbatch hpc/run_w44_q1_prepare.sbatch`
2. Pilot the first and last approved origins:
   `sbatch --array=0,25 hpc/run_w44_q1_origin.sbatch`
3. Inspect the two origin manifests, fit and prediction checksums, and logs.
   If both pass the Q1 pilot contracts, launch the remaining approved array:
   `sbatch hpc/run_w44_q1_origin.sbatch`
4. After all 26 origin manifests are `COMPLETED`, run
   `sbatch hpc/run_w44_q1_aggregate.sbatch`.

The runner checks the fixed W44 candidate and observation hashes and writes all
fits, per-node predictions, coordinates, and detailed diagnostics under
`/project/disease_ecology/STGNN-output/structured_a3_2026w44_q1_retrospective`.
Only aggregate result tables and reports are written into the repository.

The origin fit ends at each origin T. Detection-history inputs are taken from
the T-causal T+1 feature row and held fixed over horizons 1–3. Environmental
inputs obey the approved origin-time proxy rules. Since source publication
timestamps are unavailable, the run is a retrospective updated-vintage
hindcast, not operationally prospective evidence.

Current observation reporting maturity is not certified. The runner retains
metrics as descriptive diagnostics and records no predictive qualification
decision unless a separate authoritative maturity review supports scoring.
The Q1 execution does not refit the full W44 candidate, change production
configuration, or run Q2/Q3.
