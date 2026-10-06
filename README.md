# STGNN

Spatiotemporal disease-ecology modeling for weekly insect presence/absence and positive counts on a revised spatial domain.

## Project objective

Estimate weekly insect occurrence and positive counts for 10,037 revised-domain cells using environmental, livestock, anthropogenic, soil, calendar, and causal detection-history covariates.

## Current canonical modeling approach

The current development specification is **STRUCTURED A3**, a structured hurdle model with:

- Bernoulli occurrence likelihood;
- zero-truncated negative-binomial positive-count likelihood;
- 34 predictors;
- fixed `theta = 0.7018903965556372`;
- regularization penalty `0.01`; and
- exact objective `exact_joint_hurdle_nll`.

The 34 predictors are the frozen 30-feature V2-A/A0 reference plus road density, nighttime illumination, clay at 0–15 cm, and the WV0033-minus-WV0010 water-retention contrast. See [docs/current_model_specification.md](docs/current_model_specification.md) and [docs/predictor_dictionary.csv](docs/predictor_dictionary.csv).

## Spatial and temporal domain

The canonical domain is 10,037 25 × 25 km cells covering Mexico and the United States south of 40°N at weekly resolution. Protected source data and large generated artifacts remain on Atlas; their locations and provenance are documented in [docs/data_and_artifact_map.md](docs/data_and_artifact_map.md).

## Development status

- F1–F4 development selection is complete.
- STRUCTURED A3 is frozen as the current development specification.
- The 2026-W17–2026-W29 result is a supported historical exposed holdout, not an independent prospective evaluation.
- Independent prospective validation is not yet available because complete A3 predictor support ends at 2026-W29.
- Neural and GConvGRU/graph approaches were evaluated diagnostically but did not meet the current probabilistic validity requirements and are not the active production-development path.

The concise scientific decisions are recorded in [docs/modeling_decisions/](docs/modeling_decisions/). Historical V1/V2-A documents remain available for provenance and are labeled or linked as historical where appropriate.

## Repository layout

- `R/`: reusable domain, grid, graph, and observation-audit functions.
- `python/`: likelihoods, metrics, contracts, and smoke-test helpers.
- `scripts/`: reproducible data, front-feature, and validation entry points.
- `analysis/`: selected canonical A3 development and evaluation code plus compact provenance artifacts.
- `hpc/`: Atlas environment and SLURM wrappers.
- `tests/`: Python and R tests and contract checks.
- `docs/`: current specification, predictor dictionary, artifact map, decision history, and historical records.

## Repository reconciliation

The controlled reconciliation is being prepared on `feature/repository-reconciliation` from `main` at `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`. Branch ancestry, classifications, canonical component ownership, integration actions, and cleanup decisions are recorded under `docs/repository_reconciliation/`. This branch is not automatically merged to `main`.
