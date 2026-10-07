# Atlas production operations

Atlas production is pinned deliberately to an immutable release tag. The
active `main` branch is accepted development; an annotated release tag is a
scientific/software milestone; production runs use an explicitly deployed
tag. Updating `main` must not automatically change production.

## Submission

```bash
bash slurm/submit_a3_pipeline.sh --mode production_fullfit \
  --config /project/disease_ecology/STGNN-config/atlas-production.yaml
bash slurm/submit_a3_pipeline.sh --mode prospective_evaluation \
  --config /project/disease_ecology/STGNN-config/atlas-production.yaml
```

Use `--dry-run` first. The launcher creates a P0→P1→P2→P3→P4→P5 chain with
`afterok:` dependencies, prints stage/job/dependency/log information, and
writes a machine-readable submission manifest for real submissions.

`production_fullfit` determines the latest complete authorized horizon,
assembles features, fits frozen Structured A3 once, generates established
products, and finalizes QA. It is not prospective validation.

`prospective_evaluation` requires a deployed frozen-model manifest, scores only
new complete weeks after its evaluation horizon, writes to a distinct output
root, and refuses any refit command. A later, explicit full-fit run may use
those observations after review.

## Restart and cancellation

Stage manifests record run ID, stage, job ID, status, timestamps, input and
output manifest hashes. A restart must use matching model/data manifests and
may resume a valid downstream stage without refitting. Stale artifacts from a
different manifest are rejected.

Inspect a run with:

```bash
bash slurm/a3_pipeline_status.sh <run_id>
```

Cancel the chain with `scancel <job-id>` for each submitted job (or the
explicit dependency-chain IDs in the submission manifest). Cancellation does
not delete completed artifacts.
