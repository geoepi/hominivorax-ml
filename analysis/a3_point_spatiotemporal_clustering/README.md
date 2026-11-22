# STRUCTURED_A3 point-level spatiotemporal clustering investigation

This is a descriptive analysis of the corrected observation vintage used for
`STRUCTURED_A3_2026W44`. It does not fit or alter a model, change A3 inputs, or
qualify the frozen model. The primary point-level period is 2025-W01 through
2026-W44. Earlier source records are used only to construct historical
proximity summaries; observations in 2026-W45 and later are excluded.

## Data and spatial support

The analysis verifies the accepted source SHA-256 before reading observations.
It uses the existing 10,037-node A3 cell crosswalk, stored centroids, and
canonical raster affine. Original source coordinates are projected to the
existing WGS84 Albers grid for distance calculations. Points are not snapped
to cell centers. Point-to-cell assignment is independently checked by exact
reproduction of the existing 96-week A3 response-count array. The broader
environment mask is used only for grid geometry, not as the fitted model
domain.

The existing A3 domain strata (`Mexico` and `U.S.-to-40N`) are used for
regional temporal summaries. All locations and distances remain in the
original point support. Distances are in kilometres.

## Analyses

- **A — Point clustering:** within-week nearest-neighbour distances and
  strictly earlier weekly lags of 1, 2, 3, 4, 8, and 12 weeks. Regional
  summaries use same-region references.
- **B — Grid aggregation:** within-cell-week nearest-neighbour distances,
  median and maximum pairwise separation (exact for cell-weeks with at most
  50,000 pairs and a deterministic 50,000-pair sample otherwise), exact counts
  of unique pairs below 5, 10, and 25 km, short pairs crossing cell boundaries,
  and point-neighbour versus centroid distances within 5 km of a cell edge.
  Pair summaries use bounded sampling and spatial-tree counts; they do not
  construct a dense all-pairs distance matrix.
- **C — Historical proximity:** A3 cell-centroid distances to any earlier
  point in fixed 1, 3, 8, and 12 week windows, with and without points from the
  focal cell. Previous-12-week record, distinct-location, and distinct-cell
  counts are summarized within 25 and 50 km. These are compared descriptively
  with the frozen A3 history predictors and response occurrence/counts.

The response association distance bins are `<1`, `1–5`, `5–10`, `10–25`,
`25–50`, `50–100`, `100–250`, and `250+` km. Associations describe observed
patterns and are not causal estimates or model comparisons.

## Focused validation and Atlas execution

The canonical focused command runs synthetic checks for kilometre units,
self-record exclusion, strict lag eligibility, focal-cell exclusion, exact
affine crosswalk assignment, and strict pair-distance thresholds. It then
checks the actual source checksum, projection against stored centroids, grid
crosswalk, and point-assigned count reproduction:

```bash
python analysis/a3_point_spatiotemporal_clustering/scripts/run_point_clustering.py \
  --mode check --output-root "$A3_POINT_OUTPUT_ROOT"
```

The Atlas launcher `hpc/run_point_clustering.sbatch` runs that check before
the complete analysis, using the repository Python bootstrap. Set
`A3_POINT_REPO` to the isolated Atlas worktree. The default Atlas result root
is `/project/disease_ecology/STGNN-output/a3_point_spatiotemporal_clustering_w44`;
set `A3_POINT_OUTPUT_ROOT` to a new, separate path for another analysis
version or a rerun after a partial failure. Completed or partial detailed
roots are preserved and are never overwritten.

Raw point assignments, point-to-point distances, detailed cell-week features,
and boundary pairs stay below the Atlas output root. Only aggregate CSV/SVG
summaries and the written analysis report belong in this repository.

## Interpretation

This is retrospective, descriptive analysis. Observation dates do not supply
an issue-time release timestamp, so the results cannot establish prospective
availability or prospective performance. The work does not modify production
or model qualification artifacts. The final report records the evidence and
whether the proposed clustering-oriented feature family is justified,
not justified, or inconclusive.

## Results

The integrated 15-part findings and exploratory decision are in
[`point_spatiotemporal_clustering_report.md`](point_spatiotemporal_clustering_report.md).
Aggregate result tables and figures are stored in `results/` and `figures/`.
