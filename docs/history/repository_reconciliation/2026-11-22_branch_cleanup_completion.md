# 2026-11-22 branch reconciliation completion

## Scope and starting state

This record supplements the earlier repository reconciliation snapshot; it does not replace or rewrite it. The task began with 17 remote branches: the 16 audited branches in the earlier inventory plus maintenance/repository-consolidation at 00ef746161e16b47f0cda10bff89242cc7bc4a82.

PR #37 was reviewed against main at 6715a4397dad21a77414bd2ce41586751290f374. Its 38 changed files were documentation, the repository hygiene workflow, and its checker. The frozen model/configuration paths and analysis artifacts were unchanged. GitHub Actions Repository hygiene run #300 passed. PR #37 merged with the repository's merge-commit method as 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63.

PR #31 remains open and draft against main; W44 remains unpromoted.

## Deleted remote branches

Each listed tip was reverified against its designated surviving ref. The five W44 child tips were ancestors of W44 with zero unique commits relative to it. The four CHIME/P7 tips were ancestors of main with zero unique commits. The five A5/A6 tips had the unique commit counts shown and were tagged before deletion. No open PR depended on these refs. All removals used ordinary remote deletion; no force-push or history rewrite was performed.

| Branch | Tip SHA at deletion | Preserved by |
|---|---|---|
| analysis/a3-point-spatiotemporal-clustering | 901e3cfc485590af8f3d0030e83659fbe1265101 | W44 92caffc788452e6c336aa0ed81d44b2df52776cd |
| analysis/structured-a3-2026w44-cartographic-v1 | 77a0a3e2a30d5522689e467eaaf5eee9f0ff4188 | W44 92caffc788452e6c336aa0ed81d44b2df52776cd |
| analysis/structured-a3-2026w44-integrity-hardening | 8e72aa6676f1249546c6c86c9e42ff3918bdd4ab | W44 92caffc788452e6c336aa0ed81d44b2df52776cd |
| analysis/structured-a3-2026w44-q1-retrospective | 80ec27ef56f7312a9215dae0ea88eeb870718351 | W44 92caffc788452e6c336aa0ed81d44b2df52776cd |
| analysis/structured-a3-2026w44-qualification-design | 73cc5a37bcbb19e06db19bba54cb134f2bf8cc65 | W44 92caffc788452e6c336aa0ed81d44b2df52776cd |
| feature/chime-execution-correlation | 99ded2fa459e6edcf7246eabeaa947189c07554a | main 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63 |
| feature/p7-publication-finalize | 530ef4ac811a41eacc212c515d034116ef3fcd28 | main 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63 |
| feature/p7-publication-manifest | 74884fc66304a22647bd5196a5b372e00adc8311 | main 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63 |
| feature/p7a-figure-design | e51f094b2252cab28ca53a87b46c9d3d18bdb386 | main 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63 |
| feature/a5-gnn-bounded-comparison | e71c02c3ea87a4ab13dbb7733277c17b9c53c550 | historical/a5-gnn-bounded-comparison |
| feature/a5b-multiscale-component-spatial-ml | d6651a8e221e54184c68c098805300723a598276 | historical/a5b-multiscale |
| feature/a6-gpboost-correlated-spatial-ml | e734427b29111917261861a67aafa2379a5bfc07 | historical/a6-gpboost |
| feature/a6-vif-bounded-gate | 725d5b33fe4a7c2577a631dcc3fec115953f8d73 | historical/a6-vif-gate |
| codex/a6-opt-efficient | d05335ec4ab820906ce0fa78f3356ffc5170b799 | historical/a6-opt |

## Historical tag verification

All five tags are annotated, were absent before creation, were pushed without force, and were verified on GitHub by checking both the tag-object ref and peeled commit ref. The branch-specific reports, source scripts, and focused validation files exist in the corresponding tag trees. The full unique commit counts relative to the task-start main were 4, 8, 15, 24, and 23 respectively.

| Tag | Annotated tag-object SHA | Peeled branch-tip commit SHA | Unique commits |
|---|---|---|---:|
| historical/a5-gnn-bounded-comparison | 426ae07c94d5b295d13c4bbcbd3b2d87c56e13b2 | e71c02c3ea87a4ab13dbb7733277c17b9c53c550 | 4 |
| historical/a5b-multiscale | 0215ac5333ec904ae3e54eca023c5160db699fb8 | d6651a8e221e54184c68c098805300723a598276 | 8 |
| historical/a6-gpboost | 901f65e6f2e4f08aa27d96c634c01d88fb2588c0 | e734427b29111917261861a67aafa2379a5bfc07 | 15 |
| historical/a6-vif-gate | 89b36ee1fa26440bd6b0c4ba12ea55b4a40c5bf3 | 725d5b33fe4a7c2577a631dcc3fec115953f8d73 | 24 |
| historical/a6-opt | 8107cfab3f83f8491468b470071fe95369f110ac | d05335ec4ab820906ce0fa78f3356ffc5170b799 | 23 |

The A6 GPBoost tag preserves the incomplete-coverage provenance; no formal a6_decision.json was present. The A6-OPT and A6-VIF tags preserve technical gate failures, not negative predictive-performance conclusions.

## Worktrees and local refs

Ten clean worktrees were checked out on the deleted W44-child or A5/A6 branches. No worktree was removed or modified. Their local branch refs remain so those checkouts retain their current branch identity. The four older CHIME/P7 branches had no linked worktree or local branch ref. The unrelated dirty root checkout was left unchanged.

## Final refs and PRs

After git fetch origin --prune --tags, GitHub listed three remote branches at the cleanup snapshot:

1. main at 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63.
2. analysis/structured-a3-2026w44-refresh at 92caffc788452e6c336aa0ed81d44b2df52776cd.
3. maintenance/repository-consolidation, retained and reused for the follow-up cleanup-record PR.

PR #31 remains open and draft. PR #37 is merged at 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63. No W44 promotion occurred.

The separately named maintenance branch created for this task is local only; the follow-up record PR uses the already existing consolidation branch so the remote branch count remains three.

## Verification

- GitHub branch enumeration and git fetch --prune confirmed the 14 named remote refs are absent.
- Historical tag refs remain on GitHub and peel to the exact recorded commits.
- All deleted integrated branch tips remain reachable through W44 or main; every A5/A6 tip and its full unique history remains reachable through its annotated tag.
- W44 contains the PR #34, #35, and #36 merge commits and all five child branch tips.
- PR #37's merge commit is an ancestor of main.
- The cleanup changes contain no model fitting, scientific analysis, Atlas job, production model change, active configuration change, or artifact promotion.
- Focused documentation, CSV, ancestry, tag-target, remote-ref, and git diff --check validation was performed. The follow-up PR's existing repository hygiene workflow runs on its draft PR.

## Explicitly retained ref

The automatic approval review rejected deleting maintenance/repository-consolidation because it was outside the 14 named deletion targets. That ref was retained and reused for the follow-up records PR; it was not force-updated.