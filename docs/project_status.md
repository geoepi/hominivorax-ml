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

Main integration is complete at the verified no-fast-forward merge SHA `6e757b1b101d18c4cb54b580051c22397d048ff6`. The annotated milestone tag `structured-a3-development` points to that SHA and was verified locally, on GitHub, and on Atlas. The final branch cleanup verification is recorded in `docs/repository_reconciliation/final_branch_cleanup_verification.csv`. Only fully merged branches with reachable tips, no active worktree, and no unique unpreserved history were deleted; historical, active, and provenance refs remain retained.

