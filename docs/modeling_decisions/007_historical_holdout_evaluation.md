# 007 — Historical exposed holdout evaluation

## Question

How does the frozen STRUCTURED A3 model perform beyond F1–F4 without using holdout outcomes to alter the model?

## Decision

Score 2026-W17–2026-W29 as a historical exposed holdout, not as independent prospective validation.

## Evidence

The immutable evaluation manifest was frozen before evaluation outcomes. The evaluator fits only on 2025-W01–2026-W16, uses development-only preprocessing, verifies causal history cutoffs, and records a historical classification of `SUPPORTED`. Later source dates through 2026-W31 lack complete post-freeze A3 predictor support and are not eligible for an untouched prospective claim.

## Rejected alternatives

No recalibration, refit, feature-selection reopening, neural/graph fitting, or prospective claim was made.

## Provenance and status

Relevant branch/commit: `feature/structured-a3-evaluation` at `beee8ad`. The frozen manifest SHA-256 is `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61`. Status: **historical support; prospective validation pending**.
