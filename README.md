# hominivorax-ml

`hominivorax-ml` provides a statistical machine-learning workflow for weekly
spatial prediction of recorded *Cochliomyia hominivorax* detections. The
current supported model, Structured A3, is a penalized spatiotemporal hurdle
regression combining a Bernoulli occurrence component with a zero-truncated
negative-binomial positive-count component. Spatial and temporal structure are
represented through time-varying environmental predictors, seasonality,
geographically structured host and landscape covariates, and lagged
detection-history variables describing the evolving observed invasion front.

## Current supported model: Structured A3

The frozen model has 34 predictors, penalty `0.01`, fixed theta
`0.7018903965556372`, and the exact objective `exact_joint_hurdle_nll`. It
operates on the canonical 10,037-node, 25 × 25 km weekly domain covering
Mexico and the United States south of 40°N. The authoritative specification is
in [`docs/current/model.md`](docs/current/model.md), with the frozen manifest
at [`analysis/structured_a3_evaluation/results/frozen_a3_evaluation_manifest.json`](analysis/structured_a3_evaluation/results/frozen_a3_evaluation_manifest.json).

Structured A3 is spatiotemporally informed rather than a latent
spatial-random-field or graph model. Temporal dependence is represented by
time-varying covariates, seasonality, and lagged detection history; spatial
structure is represented by geographically structured predictors and dynamic
distance-to-front/history variables.

## Model outputs

The production workflow generates weekly occurrence probability, conditional
positive-count mean, and unconditional expected recorded count, together with
weekly and summary GeoTIFF products, nowcast PDFs, weekly summary tables,
interpretation figures, optional GIF animations, and an artifact manifest.
These are generated on Atlas and are not vendored in this repository.

## Study domain and temporal resolution

The model uses weekly node-level data on 10,037 canonical cells. The current
descriptive full fit covers complete data through 2026-W29. Observations extend
through 2026-W31, but complete A3 predictor support currently ends at
2026-W29.

## Model inputs

Expected schemas, transformations, and source classes are documented in
[`docs/current/data.md`](docs/current/data.md) and
[`docs/current/predictors.md`](docs/current/predictors.md). Public code and
predictor definitions are tracked here; protected observations, large derived
rasters, and Atlas-local products remain outside Git.

## Validation status

- Development is complete and the Structured A3 specification is frozen.
- The historical exposed holdout is supported under the documented rubric.
- Independent prospective validation has **not yet been tested**.
- The current descriptive full fit is not independent validation data.

Operational production functionality and scientific prospective validation are
separate claims. See [`docs/current/validation.md`](docs/current/validation.md)
and [`docs/current/limitations.md`](docs/current/limitations.md).

## Running the production workflow

Atlas users should use the limited-interaction launcher:

```bash
bash slurm/submit_a3_pipeline.sh \
  --mode production_fullfit \
  --config /project/disease_ecology/STGNN-config/atlas-production.yaml
```

For untouched weeks after a deployed frozen model’s evaluation horizon:

```bash
bash slurm/submit_a3_pipeline.sh \
  --mode prospective_evaluation \
  --config /project/disease_ecology/STGNN-config/atlas-production.yaml
```

Both modes are dependency-chained SLURM workflows. `prospective_evaluation`
never refits and writes to a distinct output root. Use `--dry-run` to validate
configuration and print the planned chain without submitting jobs. Details,
restart rules, and cancellation instructions are in
[`docs/current/atlas.md`](docs/current/atlas.md).

## Repository structure

- `analysis/`: validated analysis components and compact provenance artifacts.
- `scripts/`: reusable data, model, validation, and orchestration helpers.
- `slurm/`: release-facing Atlas submission and status wrappers.
- `config/`: tracked scientific configuration and Atlas configuration example.
- `R/`, `python/`: reusable model and data-contract code.
- `tests/`: Python, R, and orchestration contract tests.
- `docs/current/`: current supported workflow documentation.
- `docs/history/`: preserved development and audit records.

## Data availability

The repository does not distribute protected observations, large derived
rasters, or Atlas production outputs. See
[`docs/current/data.md`](docs/current/data.md) for the public/private boundary
and expected schemas.

## Limitations

The model predicts recorded detections rather than organism abundance.
Detection-history predictors describe the observed reporting/invasion state;
coefficients are conditional associations rather than causal effects. See the
full limitations statement in [`docs/current/limitations.md`](docs/current/limitations.md).

## Related projects

[`geoepi/hominivorax-geostat`](https://github.com/geoepi/hominivorax-geostat)
is a companion Bayesian joint-likelihood/geostatistical modeling workflow.
`hominivorax-ml` is the statistical machine-learning/predictive-modeling
workflow. Neither project supersedes the other.

## Development history

The release-facing documentation is intentionally not a chronological diary.
Major development records, including the original neural/GNN work, are
preserved in [`docs/history/README.md`](docs/history/README.md) and
[`docs/history/development_timeline.md`](docs/history/development_timeline.md).

## Citation / license

Authorship and citation metadata require confirmation before public release;
see [`docs/release/release_blockers.md`](docs/release/release_blockers.md).
No license file is currently present, so a license decision remains required.
