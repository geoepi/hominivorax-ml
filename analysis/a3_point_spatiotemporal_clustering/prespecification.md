# Analysis prespecification

This file fixes the descriptive scales before inspecting the W44 results.

| Choice | Prespecified value | Rationale |
| --- | --- | --- |
| Primary point period | 2025-W01–2026-W44 | Matches the frozen W44 A3 response panel. |
| Exact weekly lags | 0, 1, 2, 3, 4, 8, 12 weeks | Separates same-week clustering from short and longer weekly persistence. |
| Historical feature windows | Prior 1, 3, 8, and 12 complete ISO weeks | Reuses the same explicit temporal scales; every window ends before the target week. |
| Local concentration radii | 25 and 50 km | 25 km is approximately one nominal A3 cell width; 50 km matches the scale of an existing A3 history predictor. |
| Boundary band | At most 5 km from an A3 cell edge | Focuses the centroid comparison on observations close to a cell transition. Continuous distance differences are reported alongside descriptive 5 km, 10 km, and 2× thresholds. |
| Short point-pair thresholds | Under 5, 10, and 25 km | Describes neighbourhood pairs from fine local separation to approximately one cell width. |
| Response distance bins | `<1`, `1–5`, `5–10`, `10–25`, `25–50`, `50–100`, `100–250`, `250+` km | Reports local through regional scales while retaining a long-distance tail. |
| Historical reference | Raw source points strictly earlier than the target week | Retains point support and excludes target-week and future observations. |
| Focal-cell variant | Exclude all history points mapped to the focal model cell | Distinguishes local cell recurrence from proximity to other cells. |
| Region strata | Existing A3 `Mexico` and `U.S.-to-40N` assignments | Avoids redefining the fitted geography for this analysis. |

All distance calculations use original point coordinates projected into the
existing kilometre-based A3 CRS. Points are not snapped or rounded. The
analysis will not fit a spatial model, change a scientific parameter, or infer
prospective availability. In the absence of source release timestamps, no
prospective issue-time claim will be made.

For within-cell pairwise summaries, cell-weeks with at most 50,000 unique
pairs are enumerated exactly. Larger cell-weeks use a reproducible uniform
sample of 50,000 distinct-point pairs drawn with replacement; those medians
and maxima are labeled approximate. Exact threshold pair counts are computed
separately with spatial-tree queries.
