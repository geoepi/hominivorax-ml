# V2 observation-process audit

## Scope

Task 3A audits the recorded-detection process without fitting a V2 predictive
model. The audit uses the authoritative 136,714-row observation source and the
accepted revised domain of 10,037 nodes. The descriptive window is 2024-W01
through 2026-W29: 133 ISO weeks spanning sparse 2024 reporting, sustained 2025
reporting, and the 2026 northward expansion.

The former V1 terminal period, 2026-W17 through 2026-W29, is
`historical_evaluated_data`. It is not reused as an unseen test set or optimized
against here.

## Reporting intensity and heterogeneity

Within the audit window there were 43,052 recorded detections, 14,847 positive
node-weeks, and 1,504 nodes that were ever positive. There were no retained
observations in 2024-W01 through 2024-W46; the first two observed weeks were
2024-W47 and 2024-W50 with two detections each. This is direct evidence that the
window is not a homogeneous observation regime.

The weekly machine-readable summary reports detections, positive nodes,
occupied states and broad regions, latitude/longitude extent, convex-hull area,
occupied 25-km cells, first-ever/recurrent status, and nearest-neighbour and
prior-set distances:

`/project/disease_ecology/STGNN-output/v2_audit/observation_process/weekly_reporting_intensity.csv`

Counties were not available in the existing classification artifact; occupied
states and broad regions are reported instead.

## Persistence and repeat reporting

Across all positive node-weeks, 1,504 were first-ever positives and 13,343 were
recurrent positives. Thus 89.9% of positive node-weeks were recurrent under the
audit-window definition.

| Node-history quantity | Median | Maximum |
| --- | ---: | ---: |
| Positive weeks per ever-positive node | 6 | 69 |
| Separate positive episodes | 4 | 19 |
| Longest consecutive positive run | 2 | 69 |

The complete node history, including first/last positive week, total detections,
maximum weekly count, episode gaps, and run lengths, is
`observation_process/node_detection_history.csv`. The pattern is inconsistent
with a simple interpretation in which each zero node-week is exchangeable with
every other zero node-week: positive cells recur locally and often return after
gaps.

## Prior-distance transition diagnostic

For zero node-weeks, the following table reports the subsequent probability of
becoming positive within the stated horizon. Distance is to the nearest prior
positive node in the audit history, measured in the canonical kilometre-scaled
Albers coordinates.

| Prior distance | 1 week | 4 weeks | 13 weeks |
| --- | ---: | ---: | ---: |
| Never previously exposed | 0.000002 | 0.000013 | 0.000157 |
| 0–25 km | 0.161620 | 0.414332 | 0.680439 |
| 25–50 km | 0.033656 | 0.170561 | 0.522057 |
| 50–100 km | 0.014180 | 0.080273 | 0.377803 |
| 100–250 km | 0.002335 | 0.018781 | 0.170919 |
| >250 km | 0.000009 | 0.000093 | 0.001276 |

The same structure appears in the time-since-nearby-detection summaries. At
50 km, zero node-weeks with a detection 1–3 weeks earlier had 1-, 4-, and
13-week transition probabilities of 0.154358, 0.406597, and 0.688939; never-
exposed zero node-weeks had 0.000212, 0.001286, and 0.007724.

These are descriptive transitions, not fitted risks and not evidence of
biological dispersal. They do show that the recorded-detection background is
strongly structured by prior reporting proximity and recency.

## Environmental comparison

For 2025-W01 onward, when the existing dynamic covariate arrays are available,
first-ever and recurrent positive node-weeks were compared with zero node-weeks.
Using the temporally matched random background as a descriptive reference,
examples of positive versus background means were:

| Variable | Positive mean | Background mean |
| --- | ---: | ---: |
| `era5_mintemp` | 18.36 | 11.03 |
| `era5_soilmoist` | 0.279 | 0.225 |
| `era5land_tmean` | 23.55 | 19.66 |
| `cattle_density` | 30.55 | 13.85 |

The full first/recurrent/zero feature table is
`observation_process/environmental_first_recurrent_zero_summary.csv`. These
differences are descriptive and confounded by geography, time, reporting, and
the fact that detections are conditioned on being observed.

## Reporting proxies and identifiability

Existing holdings provide state, broad region, host category, coordinates, and
the ecological/livestock predictors already used in V1. No road density,
night-light, human-population, accessibility, survey-effort, known-at-risk, or
repeated-negative denominator was found in the project holdings searched for
Task 3A. The inventory is
`tables/reporting_proxy_inventory.csv`.

A conceptual two-process model would be:

```text
latent local occurrence/intensity -> probability of recorded detection
```

With the current data, an observation probability cannot be separated from a
latent occurrence probability without an observation denominator, repeated
negative surveys, known-at-risk units, or externally validated reporting
proxies. State and region labels are not sufficient because they are also
strongly confounded with ecology and geography. A latent occupancy/observation
model is therefore not identifiable as a production model in Task 3A.

## Point-process audit

A discrete recorded-detection intensity model could be written conceptually as

```text
Y_it ~ Poisson or negative-binomial(lambda_it)
log(lambda_it) = environment + static hosts + seasonality
                  + causal front state + spatial/random effect
```

Here `lambda_it` would mean expected recorded detections for a node-week, not
true biological abundance or latent occurrence. This formulation is compatible
with counts and repeated detections, but it still requires an explicit decision
about reporting interpretation and validation. No such model was implemented
or fitted in Task 3A.

## Conclusion

The zero-label audit finds substantial temporal and spatial heterogeneity. All
zero node-weeks should not be treated as exchangeable without a clearly stated
recorded-detection estimand. Existing data support descriptive front-history
features and possibly a recorded-intensity formulation, but do not identify a
separate latent observation process.
