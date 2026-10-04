# STGNN Repository Checkpoint — V2-A

## Checkpoint

- Checkpoint date: 2026-10-04
- Integration branch: `integration/pre-main-v2a`
- Validated integration tip: `2246cd1b690df1058922a05bf3a3504f9247ddbe`
- Frozen model ID: `STGNN-Hurdle-V2A`
- Frozen model manifest SHA-256: `1ba5c7663a5e9578c79a2e6cd1c872916665ff3b9a9ce51548745109e6e70874`

## Current operational status

The completed STGNN development chain through Task 3E is ready for consolidation
on `main`. The V2-A statistical specification remains development-frozen:
candidate M1, 30 predictors, penalty 0.01, and the frozen global dispersion
parameter are unchanged. Repository reconciliation fits no models and does not
alter coefficients, feature ordering, preprocessing, training data, prospective
ledger state, or frozen prediction artifacts.

## Prospective evaluation status

The delayed prospective harness and availability-causal contracts are operational
and remain **awaiting independent prospective evaluation**. No genuinely
independent delayed prospective nowcast has been scored yet. The Task 3E W23 and
W26 pseudo-nowcast reconstructions use persisted historical predictions and are
explicitly non-independent; they are not prospective validation evidence.

## Raster-output status

Task 3E is complete under
`/project/disease_ecology/STGNN-output/v2_rasters/`. It contains the canonical
202 x 293 raster geometry, 10,037 modeled cells, weekly probability/expected-count/
conditional-positive-count rasters for 2026-W17 through 2026-W29, selected
prediction-only pseudo-nowcast rasters, publication-ready figures, manifests,
checksums, and QA. All raster geometry, masking, sampled-value, range, and
checksum-contract checks passed.

## Known unresolved items

- No genuinely independent delayed prospective nowcast has been scored yet.
- `road_density` is not currently included.
- `night_illumination` is not currently included.
- Soil-predictor screening is occurring separately and is not part of this
  checkpoint; no pending soil predictor is an accepted predictor here.
