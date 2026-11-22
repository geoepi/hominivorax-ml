# W44 pull-request integration plan and results

## Dependency sequence

PR #35 descends from the qualification-design commits in PR #34. PR #36 is an
independent completed point-level investigation against the W44 refresh.
Integration therefore followed #34, #35, then #36, all targeting
`analysis/structured-a3-2026w44-refresh`.

| PR | Scope | Validation and diff review | Integration |
|---|---|---|---|
| #34 | Design-only W44 scientific qualification plan, evidence inventory, design matrices, and execution plan. Eight new design files; no fit or model/configuration change. | Head `73cc5a37bcbb19e06db19bba54cb134f2bf8cc65`; mergeable and clean. Existing run 276 succeeded. PR record reports JSON/CSV parsing, row counts, internal links, and diff checks passed. | Merged first using a merge commit, `84ad1639a2ce2fb29b69cf08310ca6971841abfb`. |
| #35 | Q1 retrospective implementation and aggregate-only results. Post-#34 comparison contained five unique commits and 27 added files: runner/resource metadata, Slurm wrappers, aggregate CSV/JSON/Markdown, and a focused test. No row-level predictions or coordinates were added to Git. | Head `80ec27ef56f7312a9215dae0ea88eeb870718351`; post-merge-base comparison showed five commits, all added paths, no overlapping implementation. Existing run 282 succeeded. Six focused Q1 tests and shell syntax checks had passed on Atlas. | Merged second using a merge commit, `d46d73a05cd01788f393184eca779ea9785ef511`. |
| #36 | Completed descriptive point-level clustering study, prespecification, aggregate tables/figures, report, and runner. Post-#35 comparison contained ten commits and 23 added paths. | Head `901e3cfc485590af8f3d0030e83659fbe1265101`; comparison showed only new point-study paths. Existing run 293 succeeded. The source PR reports its scoped synthetic/data-integrity checks and full descriptive study complete. | Merged third using a merge commit, `92caffc788452e6c336aa0ed81d44b2df52776cd`. |

PR descriptions and commit provenance were retained. Drafts were marked ready
as required to merge; the pull requests closed as merged. No merge to `main`
occurred. PR #31 remains open and draft.

## Resulting W44 scientific record

The consolidated W44 branch now preserves the qualification design, Q1
retrospective aggregates and code, and complete point-level clustering report
and aggregates alongside previously merged cartography and integrity
hardening. Q1 results remain descriptive because outcome maturity is
uncertified. Point proximity remains a completed descriptive investigation,
not a model change or causal/covariance estimate. W44 remains unpromoted.
