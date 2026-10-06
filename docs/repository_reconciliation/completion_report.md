# Repository reconciliation completion report

## Repository

| Field | Result |
|---|---|
| Reconciliation branch | `feature/repository-reconciliation` |
| Starting main SHA | `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1` |
| Integration content commit before this report | `87b658ca9a9e5faac1fc9eb8e0a0919b3173b77c` |
| Final reconciliation SHA | Final branch tip containing this report; reported with the completed GitHub verification |
| Remote SHA | Verified equal to the final local branch tip after publication |
| Working tree | Clean after final verification |
| Main merge | Not performed |

## Inventory

- Local refs audited: 8, including the reconciliation worktree.
- Remote refs audited: 19, excluding `origin/HEAD`.
- Branches with unique commits beyond `main`: controlled augmentation, soil screening, A3 ablation, model-class diagnostic, neural A0 audit, structured A3 final comparison, and structured A3 evaluation.
- Fully merged refs: preflight/domain audit, revised-domain baselines, hurdle-loss audit, structured revised-domain, terminal evaluation, V2 delayed-nowcast/front/observation/prospective/raster branches, and `integration/pre-main-v2a`.
- Historical experimental refs: soil screening, model-class diagnostic, neural A0 audit, and A3 ablation.
- Active canonical refs: `main`, `feature/controlled-predictor-augmentation`, `feature/structured-a3-final-comparison`, `feature/structured-a3-evaluation`, and this reconciliation branch.

## Canonical state

- Current model: **STRUCTURED A3** structured hurdle model.
- Predictor count: 34.
- Domain: 10,037 revised 25 × 25 km nodes, Mexico plus U.S. south of 40°N.
- Development status: complete; specification frozen.
- Historical holdout: `SUPPORTED` for exposed 2026-W17–2026-W29.
- Prospective status: `NOT YET AVAILABLE`; complete A3 predictor support ends at 2026-W29.
- Frozen protocol: penalty `0.01`, fixed theta `0.7018903965556372`, objective `exact_joint_hurdle_nll`.

## Integration summary

### Branches merged

- `feature/controlled-predictor-augmentation` — full history merged with a merge commit.

### Branches selectively cherry-picked

- `feature/structured-a3-final-comparison` — framework, configured helper correction, F1–F4 results, and final freeze report; duplicate helper-add commit omitted because the controlled branch supplied the file.
- `feature/structured-a3-evaluation` — frozen evaluation manifest, schemas, evaluator, fixes, and compact historical results; replayed augmentation/final-comparison imports omitted.

### Branches represented by documentation only

- `feature/soil-feature-screening` — soil conclusion and provenance retained; protected/large node tables not integrated.
- `feature/model-class-diagnostic`, `feature/neural-a0-architecture-audit`, and `feature/stgnn-a3-ablation` — negative/diagnostic neural and graph evidence retained as historical decision records.

## Complete branch disposition

| Branch | Tip or tips | Unique commits | Classification | Integrated? | Final action |
|---|---|---:|---|---|---|
| `main` | `88bcf3a` | 0 | CANONICAL-INTEGRATE | Base | RETAIN |
| `integration/pre-main-v2a` | `88bcf3a` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/atlas-preflight-data-contract` | `45842f9` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/revised-domain-audit` | local `45842f9`; remote `e18777f` | 0 / 0 | FULLY-MERGED | Yes | NO-ACTION; refs need later cleanup review |
| `feature/revised-domain-baselines` | `ab98f7c` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/hurdle-loss-audit` | `a7b22cb` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/structured-revised-domain` | `5e58f4b` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/terminal-evaluation` | `19886ca` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/v2-delayed-nowcast` | `ea4ba55` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/v2-front-hurdle` | `6644312` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/v2-observation-front-audit` | `d8aba83` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/v2-prospective-harness` | `0c65631` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/v2-raster-outputs` | `2246cd1` | 0 | FULLY-MERGED | Yes | NO-ACTION |
| `feature/soil-feature-screening` | `97defc7` | 22 | SUPERSEDED-BUT-PRESERVE | Documentation only | RETAIN historical |
| `feature/controlled-predictor-augmentation` | `bd8346f` | 7 | CANONICAL-INTEGRATE | Yes | RETAIN active until main merge decision |
| `feature/structured-a3-final-comparison` | `93ecc92` | 6 | CANONICAL-INTEGRATE | Selective | RETAIN provenance |
| `feature/structured-a3-evaluation` | `beee8ad` | 9 | CANONICAL-INTEGRATE | Selective | RETAIN provenance |
| `feature/model-class-diagnostic` | `844589d` | 2 | HISTORICAL-EXPERIMENT | Documentation only | RETAIN historical |
| `feature/neural-a0-architecture-audit` | `45dd7fe` | 7 | HISTORICAL-EXPERIMENT | Documentation only | RETAIN historical |
| `feature/stgnn-a3-ablation` | local `fc7c17d`; remote `4797edf` | 5 / 13 | HISTORICAL-EXPERIMENT | Documentation only | RETAIN historical; review divergent refs later |
| `feature/repository-reconciliation` | final branch tip | reconciliation commits | ACTIVE-FUTURE-WORK | In progress/completed | RETAIN active pending review |

The machine-readable full tables are `branch_inventory.csv`, `branch_relationships.csv`, and `branch_disposition.csv` in this directory.

## Documentation delivered

- Root `README.md` updated for current STRUCTURED A3 status.
- `docs/current_model_specification.md`.
- `docs/predictor_dictionary.csv`.
- `docs/data_and_artifact_map.md`.
- `docs/project_status.md`.
- Seven concise decision records under `docs/modeling_decisions/`.
- `docs/milestones/structured_a3_development_milestone.md`.
- Branch inventory, relationship, canonical-component, integration-plan, cleanup-audit, disposition, and completion-report artifacts.
- `.gitignore` updated to exclude caches, outputs, protected data, and credentials while allowing selected compact A3 artifacts.

## Tests and checks

| Check | Result |
|---|---|
| Python syntax/compileall | PASS |
| Atlas Python imports | PASS; fixed theta `0.7018903965556372`, 34 predictors |
| Atlas dependency-available Python tests | PASS; 53 passed, 4 warnings |
| Torch-dependent Python modules | NOT RUN; Atlas project venv has no `torch` |
| R testthat suite | PASS; 60 passed, 1 environment-dependent skip |
| Outcome-blind frozen A3 preflight | PASS; required Atlas artifacts present, no responses/metrics loaded |
| Git whitespace check | PASS |
| Frozen evaluation manifest | PASS; SHA-256 `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61` |
| Protected/large data audit | PASS; no raw rasters, Parquet/NPY data, checkpoints, credentials, or files over 1 MiB committed |

## Proposed branch cleanup

- Safe to delete now: none during this first pass; no remote branches were deleted.
- Retain historical: soil screening, model-class diagnostic, neural A0 audit, A3 ablation, structured final-comparison, and structured evaluation branches.
- Retain active: `main`, controlled augmentation, this reconciliation branch, and the provenance branches until review.
- Needs review before any cleanup: divergent local/remote `feature/revised-domain-audit` and `feature/stgnn-a3-ablation` refs.

## Boundary checks

```text
model refitted during reconciliation: NO
feature selection reopened: NO
scientific results changed: NO
protected data committed: NO
raw rasters committed: NO
credentials committed: NO
large checkpoints committed: NO
historical failed experiments erased: NO
published branch history rewritten: NO
main force-pushed: NO
main merged: NO
```

## Main merge status

`REPOSITORY RECONCILIATION READY FOR MAIN MERGE`

This is a readiness statement only. A separate explicit authorization is still required to merge the reconciliation branch into `main`.
