# Project status

## Current scientific state

| Item | Status |
|---|---|
| CURRENT MODEL | Structured A3 |
| DEVELOPMENT | Complete; STRUCTURED A3 development specification frozen |
| HISTORICAL HOLDOUT | Supported under the historical exposed-holdout rubric |
| PROSPECTIVE VALIDATION | Not yet tested; complete A3 predictor support ends at 2026-W29 |
| NEURAL/GNN MODELS | Evaluated and not supported for the current task |
| DOMAIN | 10,037 revised 25 × 25 km nodes, Mexico plus U.S. south of 40°N |
| PREDICTORS | 34 |
| CORE PROTOCOL | Fixed theta `0.7018903965556372`, penalty `0.01`, exact joint hurdle NLL |

## Interpretation boundary

The 2026-W17–2026-W29 result is a historical exposed holdout because that horizon was previously visible in project reports and development artifacts. It is not an independent prospective result. Later observations through 2026-W31 do not qualify as untouched prospective validation because the source snapshot predates the freeze and complete A3 predictor support ends at 2026-W29.

## Next scientific step

Extend complete predictor support beyond the freeze boundary and perform a genuinely untouched prospective evaluation without changing the frozen model before scoring.

## Repository state

This status is being finalized on `feature/repository-reconciliation`, created from `main` at `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`. The final reconciliation SHA and remote SHA are recorded after integration. No automatic merge to `main` is performed.
