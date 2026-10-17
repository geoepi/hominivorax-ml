# Frozen A4-S challenger and deferred independent validation

## Executive summary

The completed controlled architecture comparison concluded **HOLD — NO A4
CANDIDATE JUSTIFIED**. A4-S was the strongest provisional challenger because it
reduced the positive-count and residual-spatial diagnostics while preserving the
main A3 occurrence metrics in the pre-W30 folds. It was not advanced: U.S.
positive-risk ranking was not assessable in those folds, residual dependence
remained, and the observation process was not identified.

This workstream freezes that exact A4-S specification for a later, independent
comparison with production A3. It does not deploy A4-S, refit A3, tune A4-S,
use W30–W39 as an independent test, or add reporting or SIT covariates.

## Why A4-S was frozen but not advanced

The comparison at merge SHA `93f7ce1aef603f63eab5aecc5bbaaa6ce6bba1fc`
identified A4-S as the leading challenger. In the authorized F1–F4
development folds it improved mean PR-AUC, Brier skill, joint NLL, conditional
count bias, and positive-count residual Moran’s I relative to A3. Those are
development/comparison results, not independent evidence. The comparison also
found that U.S. ranking was not estimable because the development folds had no
U.S. positive node-weeks, and observation/reporting heterogeneity remained
unidentified. Accordingly, the correct status is a provisional frozen
challenger, not an advancement or deployment decision.

## Frozen challenger specification

The freeze script imports the reviewed A4 comparison implementation and calls
the selected `A4-S` path exactly once on the authorized 68-week endpoint
`2025-W01`–`2026-W16`. It materializes the selected graph residual effects and
stores them in the protected external Atlas artifact:

`/project/disease_ecology/STGNN-output/a4s_challenger_freeze_2026-10-17/`

The compact tracked contract is
`results/frozen_a4s_challenger_manifest.json` with its SHA-256 sidecar. The
artifact contains the 34 ordered predictor coefficients, development-only
scaling, fixed `theta = 0.7018903965556372`, penalty `0.01`, graph-Laplacian
lambda `0.5`, residual scale `1.0`, and the conjugate-gradient solver contract
(`rtol=1e-8`, `atol=1e-10`, `maxiter=500`). The graph is the canonical
10,037-node `edges_queen.parquet` domain with isolated nodes allowed.

The objective is the exact joint hurdle negative log likelihood: Bernoulli
occurrence plus zero-truncated negative-binomial positive counts. The spatial
component is a centered, graph-smoothed residual correction; it is not a new
neural architecture and is not retuned after freeze.

## Evaluation boundary and protocol

The challenger freeze boundary is `2026-W42`, with the first eligible future
week `2026-W43`. The fitting endpoint ends at `2026-W16`; weeks W17–W42 are not
used to fit or select the challenger. W30–W39 are explicitly forbidden as an
A4-S independent evaluation because A4-S was selected in a workstream informed
by A3 diagnostics over that period. A later evaluation must use only outcomes
arriving after the freeze boundary.

`scripts/evaluate_frozen_a3_vs_a4s.py` requires `--no-refit`, validates both
frozen manifests and artifact checksums, constructs the identical eligible
node-week set, and scores A3 and A4-S without recalibration, threshold tuning,
feature selection, or parameter updates. It supports `--plan-only` while no
eligible post-freeze outcomes exist. The future paired comparison is not run by
this freeze task.

Minimum support before an advancement decision is allowed:

- 8 eligible weeks;
- 50 positive node-weeks overall;
- 25 U.S. positive node-weeks for interpreting the U.S. ranking guardrail.

If U.S. support is below 25 positive node-weeks, U.S. ranking is reported as
`NOT ASSESSABLE` and A4-S is not failed solely on that unavailable endpoint.

## Pre-registered advancement rules

The rules in `config/a3_vs_a4s_advancement_rules.yaml` are fixed before future
outcomes are read. A4-S must not materially degrade PR-AUC (more than 0.02),
Brier skill (more than 0.02), calibration intercept or slope (absolute change
over 0.25), or worst-week PR-AUC (more than 0.03). It must show a material
reduction of at least 0.05 in both occurrence and positive-count residual
Moran’s I, unless a pre-registered estimability exception is documented.
Joint NLL may not worsen by more than 0.02 and positive-count NLL by more than
0.10; absolute count bias reduction of at least 0.25 is a supporting target,
not a sufficient advancement criterion by itself. U.S. median positive-risk
percentile may not fall by more than 5 percentage points and top-k recall may
not fall by more than 0.10 when U.S. support is estimable.

Temporal block bootstrap, when used, is by week with 199 replicates and seed
20261017. Random row-wise resampling is prohibited.

## Observation-process assessment and limitations

No usable surveillance-effort, reporting-source, sampling-program, inspection,
or reporting-frequency proxy was available in the authorized inputs. A4-O is
therefore not introduced here. Recorded detections may reflect heterogeneous
underreporting and observation effort, so the frozen challenger makes no claim
of estimating latent incidence or true abundance. Count agreement alone cannot
justify advancement.

SIT covariates are deliberately excluded. The status is
`RESERVED_FUTURE_INTERVENTION_LAYER`. U.S. occurrence ranking is the primary
transfer endpoint; U.S. raw count magnitude and northward progression are
secondary and explicitly `INTERVENTION_CONFOUNDED`. Low U.S. counts or slow
progression are not interpreted as pure model failure.

## Deployment status

Production remains **STRUCTURED A3**. A4-S is
**PROVISIONAL_FROZEN_CHALLENGER** only. A later task must complete the eligible
post-freeze paired evaluation and make exactly one decision: `ADVANCE A4-S`,
`RETAIN A3`, or `CONTINUE HOLD — INSUFFICIENT EVIDENCE`. This task does not
deploy A4-S.

## Validation

The focused contract tests cover the exact boundary, W30–W39 exclusion, no-SIT
and no-reporting-covariate rules, manifest byte integrity, no-refit enforcement,
and pre-registered support/threshold presence. The repository-defined hygiene
check remains the hosted CI gate for this analysis-only branch.
