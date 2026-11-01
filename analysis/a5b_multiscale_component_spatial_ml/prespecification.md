# A5B Multiscale Component-Specific Spatial ML

This is a `DEVELOPMENT_INFORMED_FOLLOWUP` to the completed A5 comparison. It
uses only the established 2025-W01--2026-W16 development boundary and F1--F4
temporal folds. Because the architecture was designed after inspecting A5 on
those folds, the results are not independent validation and can only justify
freezing a provisional challenger for a later independent evaluation.

## Candidates

- `STRUCTURED_A3`: the immutable A3 reference.
- `STRUCTURED_A4S_CHALLENGER`: the completed A5 compact reference.
- `A5-GNN-NOPE`: the completed A5 compact reference.
- `A5B-MS-OCC`: four exact graph-distance shell operators, each with hidden
  width 8, concatenated into a shallow occurrence residual head. The count
  component remains A3.
- `A5B-HYBRID`: the same occurrence model with the immutable frozen A4-S
  positive-count component, only when the frozen artifact is extractable
  without refitting.

The A5B network receives the standardized 34 A3 predictors plus the A3
occurrence and positive-count linear predictors. It does not receive
coordinates, Laplacian eigenvectors, node embeddings, outcomes, residuals, or
future-derived quantities. Each target-week correction is centered across the
eligible training nodes before being added to the A3 occurrence offset.

## Spatial contract

The only spatial primitive is the canonical 10,037-node, 77,614-directed-edge
queen graph. Exact shortest-path shells 1--4 are constructed deterministically
from that graph, with pair counts and SHA-256 hashes recorded. The shell
relations are not learned and never use response values.

## Endpoints and decision

The primary endpoint is occurrence residual Moran's I at shells 1--4. Shell 1
must improve by at least 0.05 relative to A3, and shells 2--4 may not worsen by
more than 0.01. Predictive guardrails, temporal residuals, full-hurdle
residuals, frontier summaries, seed stability, and the secondary spatial
stress test are reported. The decision is one of the four specified A5B
development outcomes and does not authorize deployment.
