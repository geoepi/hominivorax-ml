# Repository reconciliation completion report

## Repository integration

| Field | Result |
|---|---|
| Starting main SHA | `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1` |
| Reconciliation SHA before merge | `a0b9775fb88e6218d57cf7f3ee2122531c923291` |
| Main merge SHA | `6e757b1b101d18c4cb54b580051c22397d048ff6` |
| Merge method | `--no-ff`; parents were starting main and reconciliation; no conflicts |
| GitHub main SHA | Equal to local main at merge and after cleanup documentation pushes |
| Milestone tag | `structured-a3-development`, annotated and pushed; peeled target `6e757b1b101d18c4cb54b580051c22397d048ff6` |
| Atlas pre-execution SHA | Equal to local and GitHub main at `6e757b1b101d18c4cb54b580051c22397d048ff6` |
| Local user checkout | Preserved dirty on `feature/soil-feature-screening`; never checked out or merged |
| Final branch tip | Reported by the final GitHub verification and recorded with the cleanup artifacts in this commit sequence |

## Canonical scientific state

- Current model: **STRUCTURED A3** structured hurdle model.
- Predictor count: 34.
- Domain: 10,037 revised 25 × 25 km nodes, Mexico plus U.S. south of 40°N.
- Development status: complete; specification frozen.
- Historical holdout: `SUPPORTED` for exposed 2026-W17–2026-W29.
- Prospective status: `NOT YET AVAILABLE`; complete A3 predictor support ends at 2026-W29.
- Frozen protocol: penalty `0.01`, fixed theta `0.7018903965556372`, objective `exact_joint_hurdle_nll`.

## Integration summary

The main merge includes the controlled predictor augmentation, selected structured A0/A3 comparison and freeze work, frozen-manifest evaluator and compact historical exposed-holdout artifacts, and documentation-only scientific decisions for soil and historical neural/graph work. No scientific refit or model-selection reopening occurred.

## Branch cleanup

- Deleted local branches: `feature/atlas-preflight-data-contract`, `feature/revised-domain-audit`.
- Deleted remote branches: those two names plus `feature/revised-domain-baselines`, `feature/hurdle-loss-audit`, `feature/structured-revised-domain`, `feature/terminal-evaluation`, `feature/v2-delayed-nowcast`, `feature/v2-front-hurdle`, `feature/v2-observation-front-audit`, `feature/v2-prospective-harness`, `feature/v2-raster-outputs`, and `integration/pre-main-v2a`.
- Every deleted tip was verified reachable from main, unused by an active worktree, and free of unique unpreserved history.
- Retained: main, controlled augmentation, reconciliation, structured final-comparison, structured evaluation, soil screening, model-class diagnostic, neural A0 audit, and STGNN ablation refs.
- The clean temporary Atlas post-merge verification worktree was removed. User and historical/provenance worktrees were preserved.
- The complete decision record is `docs/repository_reconciliation/final_branch_cleanup_verification.csv`.

## Tests and integrity checks

| Check | Result |
|---|---|
| Local bundled Python compileall | PASS |
| Local bundled Python imports | Environment-limited: bundled runtime lacks SciPy |
| Atlas Python compileall/imports | PASS; fixed theta `0.7018903965556372`, 30 base plus 4 A3 predictors |
| Atlas dependency-available Python tests | PASS; 53 passed, 4 warnings |
| Torch-dependent Python modules | NOT RUN; Atlas project venv has no `torch` |
| Local R testthat suite | PASS; 60 passed, 1 environment-dependent skip |
| Outcome-blind frozen A3 preflight | PASS; `READY_FOR_OUTCOME_BLIND_DATA_AUDIT`; required artifacts present; no responses or metrics loaded |
| Frozen evaluation manifest | PASS; SHA-256 `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61` locally and on Atlas |
| GitHub transfer boundary | PASS; only intended compact repository source/artifacts transferred through GitHub |
| Protected/large data audit | PASS; no raw rasters, Parquet/NPY data, checkpoints, credentials, or generated outputs committed |

## Boundary checks

```text
model refitted during integration: NO
feature selection reopened: NO
scientific results changed: NO
protected data committed: NO
raw rasters committed: NO
credentials committed: NO
large checkpoints committed: NO
historical failed experiments erased: NO
published branch history rewritten: NO
main force-pushed: NO
```

## Final status

`MAIN INTEGRATION AND BRANCH CLEANUP COMPLETE`

