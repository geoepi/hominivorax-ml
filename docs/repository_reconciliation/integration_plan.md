# Repository reconciliation integration plan

This is the pre-integration gate for `feature/repository-reconciliation`, created from `main` at `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`. The plan deliberately separates canonical integration from historical retention. No remote branch deletion or `main` merge is authorized in this pass.

| Branch/ref | Classification | Unique commits | Canonical content | Integration action | Proposed commits / reason | Remote disposition |
|---|---|---:|---|---|---|---|
| `feature/controlled-predictor-augmentation` | CANONICAL-INTEGRATE | 7 | Road/night aggregation, A3 augmentation helper, fixed-theta baseline provenance | MERGE | Merge the direct descendant; it supplies the reusable four-feature augmentation implementation. | RETAIN active until canonical branch is accepted |
| `origin/feature/structured-a3-final-comparison` | CANONICAL-INTEGRATE | 6 | F1–F4 A0/A3 comparison, A3 manifest, development freeze decision | CHERRY-PICK | Cherry-pick `233029b`, `a018674`, `e47b8a4`, `faf5bf6`, `93ecc92`; omit duplicate helper-add commit `89c9185` because the controlled branch supplies the file. | RETAIN as provenance until canonical branch is accepted |
| `origin/feature/structured-a3-evaluation` | CANONICAL-INTEGRATE | 9 | Frozen evaluation manifest, evaluator, historical exposed holdout results | CHERRY-PICK | Cherry-pick `0457ca2`, `72e8e5b`, `134e89d`, `e345ea1`, `5525cd3`, `f2be779`, `beee8ad`; omit replayed augmentation/final-comparison imports `ad73b19` and `abea8e3`. | RETAIN as evaluation provenance |
| `feature/soil-feature-screening` | SUPERSEDED-BUT-PRESERVE | 22 | Soil-screening decisions, failure boundaries, fixed-theta soil provenance | DOCUMENT-ONLY | Do not merge wholesale: it diverges before `main` and carries protected/large soil artifacts plus older files. Preserve branch and cite commits in decision documentation. | RETAIN historical; no deletion in first pass |
| `origin/feature/model-class-diagnostic` | HISTORICAL-EXPERIMENT | 2 | Feed-forward/GRU model-class diagnostic and negative/diagnostic evidence | RETAIN-AS-HISTORICAL | Document the result; do not merge training tables or make neural code active. | RETAIN historical |
| `origin/feature/neural-a0-architecture-audit` | HISTORICAL-EXPERIMENT | 7 | Neural A0 architecture/loss validity audit | RETAIN-AS-HISTORICAL | Document invalid/unsupported neural pathway and preserve branch history. | RETAIN historical |
| `feature/stgnn-a3-ablation` local / `origin/feature/stgnn-a3-ablation` remote | HISTORICAL-EXPERIMENT | 5 / 13 | Graph/neural A3 ablation and QA evidence | RETAIN-AS-HISTORICAL | Document diagnostic result; do not merge graph training outputs or reopen model selection. | RETAIN historical; refs require review before any cleanup |
| `feature/atlas-preflight-data-contract` | FULLY-MERGED | 0 | Preflight provenance already reachable from `main` | NO-ACTION | Tip is an ancestor of `main`; retain until branch cleanup is separately approved. | Candidate for later deletion after reachability review |
| `feature/revised-domain-audit` local / remote | FULLY-MERGED | 0 / 0 | Revised-domain audit already reachable from `main` | NO-ACTION | Local and remote refs diverge but both tips are ancestors of `main`. | Candidate for later deletion after ref reconciliation |
| `origin/feature/revised-domain-baselines` | FULLY-MERGED | 0 | Revised-domain baseline history already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/hurdle-loss-audit` | FULLY-MERGED | 0 | Metric/audit history already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/structured-revised-domain` | FULLY-MERGED | 0 | Structured revised-domain predecessor already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/terminal-evaluation` | FULLY-MERGED | 0 | Historical terminal evaluation already in `main` | NO-ACTION | Tip is reachable from `main`; preserve documents as historical. | Candidate for later deletion after tag/review |
| `origin/feature/v2-delayed-nowcast` | FULLY-MERGED | 0 | Delayed-nowcast contract already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/v2-front-hurdle` | FULLY-MERGED | 0 | V2 freeze-policy history already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/v2-observation-front-audit` | FULLY-MERGED | 0 | Observation/front audit already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/v2-prospective-harness` | FULLY-MERGED | 0 | Prospective harness already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/feature/v2-raster-outputs` | FULLY-MERGED | 0 | Raster checkpoint already in `main` | NO-ACTION | Tip is reachable from `main`. | Candidate for later deletion |
| `origin/integration/pre-main-v2a` | FULLY-MERGED | 0 | Same tip as `main` | NO-ACTION | Exact duplicate of the current main tip. | Candidate for later deletion |
| `main` | CANONICAL-INTEGRATE | 0 | Current pre-reconciliation canonical checkpoint | BASE | Starting point only; do not modify directly. | RETAIN |
| `feature/repository-reconciliation` | ACTIVE-FUTURE-WORK | 0 before integration | Reconciled structured A3 documentation and selected workflow | RETAIN-ACTIVE | Working branch for this controlled pass. | RETAIN until review and main merge authorization |

## Gate decision

No branch is classified `NEEDS-REVIEW` for the planned integration itself. The divergent local/remote `feature/revised-domain-audit` refs and the divergent local/remote A3-ablation refs are explicitly retained and are not deletion candidates in this pass. If a merge conflict would overwrite newer canonical code, stop and use a selective reconstruction commit instead of forcing the merge.
