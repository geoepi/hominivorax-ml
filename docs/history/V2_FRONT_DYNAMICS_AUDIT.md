# V2 front-dynamics audit

## Audit-only status

All front descriptors in this report are diagnostic candidates. They are stored
under `v2_audit/front_states/` with the label
`AUDIT ONLY — NOT YET AUTHORIZED AS MODEL FEATURES`. No V2 predictive model was
fit and no front-distance threshold was tuned.

## Causal definitions and units

For week `t`, every descriptor uses only response observations from weeks `< t`.
The candidate definitions are:

| Candidate | Definition |
| --- | --- |
| A | Northmost observed latitude among prior positive nodes |
| B | 95th-percentile latitude among all prior positive nodes |
| C | 95th-percentile latitude among positive nodes in the prior 4 weeks |
| D | 95th-percentile latitude among positive nodes in the prior 13 weeks |
| E | Distance to the nearest node positive in any prior week |
| F | Distance to the nearest node positive in the prior 4 weeks |

Distances use the existing canonical Albers equal-area projected node coordinates.
The raster CRS explicitly declares kilometre-scaled axes, so distances and
areas are reported in kilometres and square kilometres. Candidate node-week
fields include distance to prior detections, signed distance north/south of the
prior front, and weeks since a detection within 25, 50, and 100 km.

## Candidate-front stability

The global and rolling percentile front definitions are highly correlated, but
the northmost statistic is less stable:

| Pair | Correlation |
| --- | ---: |
| A vs B | 0.9311 |
| A vs C | 0.9245 |
| A vs D | 0.9297 |
| B vs C | 0.9972 |
| B vs D | 0.9996 |
| C vs D | 0.9971 |

The complete candidate comparison and pairwise correlation tables are
`front_states/front_candidate_comparison.csv` and
`front_states/front_candidate_pairwise_correlations.csv`.

## Apparent progression

The following are distributions across weekly changes or first-positive
distances. They describe recorded detections only and are not biological
dispersal estimates.

| Quantity | Median | IQR | P90 | P95 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Northmost latitude change (km) | 0.00 | 72.67 | 128.66 | 204.61 | 561.46 |
| 95th-percentile front change (km) | 2.24 | 38.21 | 61.94 | 78.93 | 155.42 |
| Positive-set centroid displacement (km) | 25.35 | 21.78 | 59.17 | 72.05 | 127.73 |
| Principal-axis displacement (km) | -2.22 | 37.89 | 34.23 | 57.29 | 121.93 |
| First-positive distance to any prior positive (km) | 24.94 | 10.37 | 55.80 | 74.99 | 660.47 |
| First-positive distance to prior-4-week positives (km) | 24.94 | 10.37 | 55.87 | 78.90 | 847.08 |
| First-positive distance to prior-13-week positives (km) | 24.94 | 10.37 | 55.80 | 78.50 | 660.47 |

There were 1,503 first-positive nodes with an earlier positive node in the
audit window; one of the 1,504 first-positive nodes was left-censored at the
start of 2024. The complete long-jump table is
`front_states/first_positive_distance_summary.csv`, and node-level distances
are retained in the audit front-state parquet.

## One-dimensional versus two-dimensional movement

The northmost statistic can jump substantially while the 95th-percentile front
and centroid move more moderately. The correlations of northmost change with
95th-percentile change and centroid displacement were only 0.121 and 0.167.
The median nearest-new-cell direction was 121 degrees from the projected x-axis
with a standard deviation of 68.6 degrees. Centroid and principal-axis
displacements also varied in sign.

The recorded expansion therefore has a northward component, but a one-
dimensional latitude-only approximation is not sufficient as a complete
description. A causal front-history representation should retain two-
dimensional proximity or displacement information, subject to later estimand
review.

## Leakage controls

The causal constructor writes a source-history cutoff for every node-week. The
tests verify that:

- week `t` does not use the response at `t`;
- adding a future positive leaves all earlier descriptors bitwise unchanged;
- changing the current response leaves the current-week descriptors unchanged;
- only permitted future descriptors can change;
- node/week ordering is unique and complete.

These controls are prerequisites for any later V2 use; they do not authorize
the descriptors as production predictors.

## Conclusion

Prior detections provide a strong descriptive spatial signal, and the front is
not adequately summarized by a stationary surface or by latitude alone. The
most operationally stable candidates are the prior positive-set distances and
the highly correlated B–D percentile summaries. The choice among them remains
a Level-2 V2 estimand decision.
