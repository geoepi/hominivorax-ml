# Repository reconciliation integration plan

This plan governed the controlled integration of `feature/repository-reconciliation`, created from `main` at `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`. The plan deliberately separates canonical integration from historical retention. The authorized main merge and conservative cleanup are now complete; final actions are recorded in `final_branch_cleanup_verification.csv`.

| Branch/ref | Classification | Unique commits | Canonical content | Integration action | Proposed commits / reason | Remote disposition |
|---|---|---:|---|---|---|---|
| `feature/controlled-predictor-augmentation` | CANONICAL-INTEGRATE | 7 | Road/night aggregation, A3 augmentation helper, fixed-theta baseline provenance | MERGED | Direct history is reachable from main; the branch remains the active implementation/provenance ref. | RETAIN active |
| `origin/feature/structured-a3-final-comparison` | CANONICAL-INTEGRATE | 6 | F1–F4 A0/A3 comparison, A3 manifest, development freeze decision | SELECTIVE CONTENT MERGED | Selected commits are represented in main; duplicate helper-add content was omitted in favor of the controlled branch. | RETAIN as provenance |
| `origin/feature/structured-a3-evaluation` | CANONICAL-INTEGRATE | 9 | Frozen evaluation manifest, evaluator, historical exposed holdout results | CHERRY-PICK | Cherry-pick `0457ca2`, `72e8e5b`, `134e89d`, `e345ea1`, `5525cd3`, `f2be779`, `beee8ad`; omit replayed augmentation/final-comparison imports `ad73b19` and `abea8e3`. | RETAIN as evaluation provenance |
| `feature/soil-feature-screening` | SUPERSEDED-BUT-PRESERVE | 22 | Soil-screening decisions, failure boundaries, fixed-theta soil provenance | DOCUMENT-ONLY | Do not merge wholesale: it diverges before `main` and carries protected/large soil artifacts plus older files. Preserve branch and cite commits in decision documentation. | RETAIN historical; no deletion in first pass |
| `origin/feature/model-class-diagnostic` | HISTORICAL-EXPERIMENT | 2 | Feed-forward/GRU model-class diagnostic and negative/diagnostic evidence | RETAIN-AS-HISTORICAL | Document the result; do not merge training tables or make neural code active. | RETAIN historical |
| `origin/feature/neural-a0-architecture-audit` | HISTORICAL-EXPERIMENT | 7 | Neural A0 architecture/loss validity audit | RETAIN-AS-HISTORICAL | Document invalid/unsupported neural pathway and preserve branch history. | RETAIN historical |
| `feature/stgnn-a3-ablation` local / `origin/feature/stgnn-a3-ablation` remote | HISTORICAL-EXPERIMENT | 5 / 13 | Graph/neural A3 ablation and QA evidence | RETAIN-AS-HISTORICAL | Document diagnostic result; do not merge graph training outputs or reopen model selection. | RETAIN historical; refs require review before any cleanup |
| `feature/atlas-preflight-data-contract` | FULLY-MERGED | 0 | Preflight provenance already reachable from `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `feature/revised-domain-audit` local / remote | FULLY-MERGED | 0 / 0 | Revised-domain audit already reachable from `main` | CLEANUP | Both divergent tips were verified as ancestors with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/revised-domain-baselines` | FULLY-MERGED | 0 | Revised-domain baseline history already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/hurdle-loss-audit` | FULLY-MERGED | 0 | Metric/audit history already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/structured-revised-domain` | FULLY-MERGED | 0 | Structured revised-domain predecessor already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/terminal-evaluation` | FULLY-MERGED | 0 | Historical terminal evaluation already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/v2-delayed-nowcast` | FULLY-MERGED | 0 | Delayed-nowcast contract already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/v2-front-hurdle` | FULLY-MERGED | 0 | V2 freeze-policy history already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/v2-observation-front-audit` | FULLY-MERGED | 0 | Observation/front audit already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/v2-prospective-harness` | FULLY-MERGED | 0 | Prospective harness already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/feature/v2-raster-outputs` | FULLY-MERGED | 0 | Raster checkpoint already in `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `origin/integration/pre-main-v2a` | FULLY-MERGED | 0 | Same tip as pre-merge `main` | CLEANUP | Tip was verified as an ancestor with no active worktree. | DELETED-AFTER-VERIFICATION |
| `main` | CANONICAL-INTEGRATE | 0 | Verified post-merge canonical main | BASE | Main integration complete. | RETAIN |
| `feature/repository-reconciliation` | ACTIVE-FUTURE-WORK | 0 before integration | Reconciled structured A3 documentation and selected workflow | MERGED | Branch tip is reachable from main; retained for provenance. | RETAIN-AS-PROVENANCE |

## Gate decision

The merge completed without conflict. The divergent local/remote `feature/revised-domain-audit` refs were independently verified as ancestors of main and deleted because they had no active worktree or unique unpreserved history. The divergent local/remote `feature/stgnn-a3-ablation` refs remain retained as historical evidence. No scientific refit, model-selection reopening, protected-data transfer, or history rewrite occurred.
