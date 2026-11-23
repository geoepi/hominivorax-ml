# Final repository status

**Reconciliation date:** 2026-11-22.

## GitHub state

- Starting remote branch count: **17**.
- Final remote branch count at the cleanup PR snapshot: **3**.
- Surviving refs: main at 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63; analysis/structured-a3-2026w44-refresh at 92caffc788452e6c336aa0ed81d44b2df52776cd; and maintenance/repository-consolidation for draft PR #38 (current remote tip).
- PR #37 merged into main as merge commit 215aebb8bd75ac3a4f7bffbd2422bb0704a3ea63.
- PR #31 remains open and draft against main. W44 is not merged or promoted.
- The completion record is in open draft PR #38 on maintenance/repository-consolidation.

Fourteen remote refs were deleted after checking exact tips, ancestry, open PRs, and evidence preservation. Their full names and SHAs are listed in the [dated cleanup completion record](../history/repository_reconciliation/2026-11-22_branch_cleanup_completion.md) and the updated [branch inventory](branch_inventory.csv).

Five annotated tags now preserve the complete A5/A6 scientific and implementation branch histories. Exact tag names, tag object SHAs, and peeled commit SHAs are listed in the completion record. The five associated local worktrees and local branch refs remain intact. No worktree was removed.

## Scientific and production state

- Supported architecture: original W16-frozen STRUCTURED_A3.
- Active production artifact: W29 full fit according to the latest isolation record (model SHA prefix 1cb694f; active configuration SHA prefix f51038).
- Latest candidate: STRUCTURED_A3_2026W44, SHA-256 b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b, CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED.
- W44 Q1 retrospective: 26 origin fits and 78 horizon blocks; target maturity is uncertified and the scientific decision remains NOT_ASSIGNED.
- Point-level clustering remains a completed descriptive study with decision POINT_PROXIMITY_CHALLENGER_NOT_JUSTIFIED.
- No model, production artifact, active Atlas configuration, scientific fit, or qualification run was changed or executed during this branch reconciliation.

## Verification

- git fetch origin --prune --tags completed after remote branch deletion.
- GitHub branch enumeration returned three remote branches at the cleanup snapshot.
- All five historical tags are annotated and peel to the exact recorded branch-tip commits. Their reports, scripts, and validation evidence remain readable from those tag trees.
- The five subordinate W44 tips are ancestors of the surviving W44 branch; PR #34, #35, and #36 merge commits remain reachable there.
- The four CHIME/P7 tips are ancestors of main. PR #37's commit is reachable from the merged main.
- Local branch refs were retained where linked worktrees still use them. The unrelated dirty root checkout was untouched.

The pre-existing maintenance/repository-consolidation ref was outside the 14 explicitly named deletion targets. The automatic approval review rejected deleting that extra ref; it is retained and reused for the completion-record PR.
