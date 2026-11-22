# Repository reconciliation report

**Audit date:** 2026-11-22
**Repository:** `geoepi/hominivorax-ml`
**Maintenance branch:** `maintenance/repository-consolidation`
**Classification:** Category D for the complete task because it integrates already-completed scientific A3 point-clustering evidence into W44 and reconciles scientific candidate status. The new CI/documentation checker is a Category C executable validation change. No new analysis or model fit was run in this task.

## Governance and starting state

Reviewed the supplied global `AGENTS.md`, `EXECUTION_GOVERNANCE.md`,
`ATLAS_SSH_POLICY.md`, repository runbook and test instructions, the
scientific freeze and qualification policies, and existing branch/release
records. Work was performed in an isolated worktree based on `main` at
`6715a4397dad21a77414bd2ce41586751290f374`. The separate root checkout's
unrelated untracked SIT files and worktrees were not changed.

The production model specification, frozen W16 model artifacts, active
production configuration, and W44 scientific candidate identity were not
modified. No Atlas jobs were submitted, and no new scientific analysis,
candidate fit, prospective qualification, production promotion, force-push,
or remote branch deletion occurred.

## Pull-request integration

The authorized sequence was completed with merge commits into
`analysis/structured-a3-2026w44-refresh`:

1. PR #34: qualification design; merge
   `84ad1639a2ce2fb29b69cf08310ca6971841abfb`.
2. PR #35: Q1 retrospective implementation and aggregate results; merge
   `d46d73a05cd01788f393184eca779ea9785ef511`.
3. PR #36: completed point-level clustering report and aggregates; merge
   `92caffc788452e6c336aa0ed81d44b2df52776cd`.

Pre-merge previews were clean. PR #35's post-#34 comparison had five unique
commits and only Q1 files. PR #36's post-#35 comparison had ten commits and
only point-study files. The existing repository-hygiene checks succeeded on
all three PR heads. PR #31 remains open and draft against `main`, with the
W44 branch as head.

## Branch reconciliation

The GitHub branch API reported 16 branches, with `main` at the starting SHA
and W44 at `92caffc788452e6c336aa0ed81d44b2df52776cd`. Branch relationships,
unique commit lists, changed files, associated PRs, evidence preservation, and
dispositions are in [branch_inventory.csv](branch_inventory.csv). Five A5/A6
branches retain unique scientific or technical evidence and are marked
`HISTORICAL_PRESERVE`. Nine integrated branches with zero unique commits
against their canonical refs are listed as later deletion candidates in
[branch_cleanup_manifest.csv](branch_cleanup_manifest.csv). No refs were
deleted.

The branch-protection endpoint returned 403 to the connected GitHub integration.
The branch API showed unprotected flags and the rulesets collection was empty,
but required checks or organization-level controls cannot be ruled out from
those responses.

## Scientific and documentation outcomes

- The supported architecture remains the W16-frozen `STRUCTURED_A3`.
- The W29 full-fit remains the active production artifact according to the
  2026-11-19 isolation record.
- The W44 full fit remains
  `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.
- Q1 completed 26 origin fits and 78 horizon blocks. Since target maturity is
  uncertified, the scientific decision is `NOT_ASSIGNED` and its metrics are
  descriptive.
- The point-level clustering record is integrated, with final decision
  `POINT_PROXIMITY_CHALLENGER_NOT_JUSTIFIED`.
- A3–A6 decisions and the point study are consolidated in
  [the model-development decision register](../current/model_development_decisions.md).
- Current documentation now distinguishes P6 inference, the P0–P5 full-fit
  pipeline, and the W44 development candidate-refresh workflow.
- A proposed routine-refresh policy is documented but is not approved and
  does not override P0–P7 requirements.

## Validation, limits, and remaining review

Existing branch validations were reused: PR #34/#35/#36 repository-hygiene
workflow runs succeeded; PR #34 reports JSON/CSV, design-row, link, and diff
checks; PR #35 reports six focused Atlas Q1 tests and shell syntax checks; the
point investigation reports its scoped synthetic/data-integrity validation.
No new scientific checks were run.

The local Windows checkout has Git but no `python`, `python3`, `ruby`, or
`Rscript` command available. The new documentation/schema checker therefore
requires its GitHub Actions run for executable validation. It uses Python
standard library checks and Ruby's standard-library YAML parser on the
repository's Ubuntu runner; it introduces no package dependency.

The active production configuration and W44 candidate were not changed.
Current environment examples include legacy W29 source paths and a
developer-specific R library path; they are explicitly identified as
non-authoritative templates in the current documentation and remain a
separate configuration-maintenance review.

No production promotion, new qualification run, model development, policy
approval, branch deletion, or merge into `main` was performed.
