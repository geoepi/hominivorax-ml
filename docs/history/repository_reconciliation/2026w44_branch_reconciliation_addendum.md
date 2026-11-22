# W44 integration and branch-reconciliation addendum

**Audit date:** 2026-11-22. This addendum supplements the original release and
reconciliation records. Their historical findings and old branch inventory
remain intact; this document records the later W44 integration state.

## Verified repository and pull-request state

- GitHub default branch is `main`, unchanged at
  `6715a4397dad21a77414bd2ce41586751290f374`.
- The consolidated W44 branch is
  `analysis/structured-a3-2026w44-refresh` at
  `92caffc788452e6c336aa0ed81d44b2df52776cd`.
- PR #31 remains open and draft against `main`; its head is the consolidated
  W44 branch. It was not merged.
- PR #34 was merged into W44 with merge commit
  `84ad1639a2ce2fb29b69cf08310ca6971841abfb`.
- PR #35 was merged next into W44 with merge commit
  `d46d73a05cd01788f393184eca779ea9785ef511`.
- PR #36 was merged last into W44 with merge commit
  `92caffc788452e6c336aa0ed81d44b2df52776cd`.
- These merges preserved the original commits and PR descriptions. PRs #32 and
  #33 were already merged into W44 before this integration.

The order resolved the #35 dependency on #34. The post-#34 comparison showed
five Q1 commits beyond the design branch and added only Q1 runner, aggregate
outputs, Slurm wrappers, and a focused test. The post-#35 comparison showed ten
point-study commits and only new point-analysis files. Merge previews were
clean. Existing repository-hygiene workflow runs succeeded on heads for PRs
#34, #35, and #36 (runs 276, 282, and 293). No Atlas jobs or new scientific
analyses were submitted.

## Current remote branch audit

The remote audit found 16 branches and seven annotated tags. No GitHub release
was present. All branch API `protected` fields were false; the integration
could not read the explicit branch-protection endpoint (403), and the rulesets
collection was empty. Therefore this audit cannot establish that GitHub has no
required checks or organization-level controls.

The machine-readable
[branch inventory](../../repository_maintenance/branch_inventory.csv)
records every branch head, canonical comparison ref, merge base, ahead/behind
counts, unique commits, PRs, changed file paths, evidence uniqueness,
preservation method, and recommended disposition. The
[cleanup manifest](../../repository_maintenance/branch_cleanup_manifest.csv)
lists nine integrated branches with zero unique commits versus their
canonical ref as later deletion candidates. No remote branch was deleted.

Five A5/A6 development branches retain unique scientific implementation,
reports, tests, or gate evidence. They remain
`HISTORICAL_PRESERVE`; they were not bulk-merged into `main` and must not be
deleted merely because the methods were not selected. The W44 refresh remains
`ACTIVE` while PR #31 is open.

The four CHIME/P7 historical branches are fully represented in `main`.
The integrated W44 point, cartographic, integrity-hardening, qualification
design, and Q1 branches are fully represented in the consolidated W44 ref.
These facts support later deletion review only; they are not deletion
authorization.

## Preservation and production boundaries

The W44 merge contains non-production analysis code, qualification design,
Q1 aggregate results, the point-level report and aggregates, and prior
cartographic/integrity work. Row-level Q1 predictions remain on Atlas.
The W44 candidate remains
`CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`. The original W16
scientific freeze and active W29 production artifact remain unchanged, and
there is no merge from W44 to `main`.

The original
[`final_branch_reconciliation.csv`](../../release/final_branch_reconciliation.csv)
is the point-in-time release audit; this addendum and the maintenance inventory
are its later supplement.
