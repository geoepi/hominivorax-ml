# Structured A3 development milestone

## Milestone

The revised-domain structured hurdle workflow has reached a coherent frozen development state.

## Included evidence

- revised 10,037-node spatial domain;
- frozen 30-predictor V2-A/A0 reference;
- bounded soil-screening conclusion and checksummed soil artifact provenance;
- controlled road/night and soil predictor augmentation;
- fixed-theta structured A0/A3 F1–F4 comparison;
- structured A3 freeze with 34 predictors, penalty `0.01`, and fixed theta `0.7018903965556372`;
- historical exposed holdout evaluation for 2026-W17–2026-W29.

## Interpretation

The historical exposed holdout is classified `SUPPORTED` under the documented rubric. It is not an independent prospective evaluation. Complete A3 predictor support ends at 2026-W29, so the next scientific step is to extend predictor support and score a genuinely untouched later period without changing the frozen model before scoring.

## Boundary

Neural/GNN model classes were evaluated diagnostically and are not supported as the current task pathway. No feature-selection reopening, theta re-estimation, recalibration, protected-data commit, history rewrite, force-push, or automatic merge to `main` is part of this milestone.

## Provenance

The structured development decision is recorded at `93ecc92` on `feature/structured-a3-final-comparison`. The historical evaluation artifacts are recorded at `beee8ad` on `feature/structured-a3-evaluation`. This reconciliation branch deliberately preserves those source histories through selective merge/cherry-pick and documentation.
