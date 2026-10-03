# Task 2D — Revised domain audit

This document defines the audit-only implementation for the revised STGNN
analysis domain. It is intentionally separate from `model_data/`; the
original Task-2A dataset is never overwritten.

## Authoritative Atlas run

The audit completed on 2026-10-03 from Task-2C HEAD
`a7b22cb3d400b41388bc0ca150b49e0bcd264f7a` on
`feature/revised-domain-audit`. The fixed boundary rule retained 10,037 of
16,756 canonical nodes (6719 nodes removed). The original graph had 128,684
directed edges, 31 components, and 17 isolated nodes; the induced revised
graph has 77,614 directed edges, 4 components, and 3 isolated nodes. Mean
degree changed from 7.6799 to 7.7328.

Across 2024-W01–2026-W29, the revised domain has 14,820 positive node-weeks
out of 1,334,921 (1.1102%) and 1,480 occupied nodes, compared with 34,129 out
of 2,228,548 (1.5314%) in the original domain. The revised 2025-W01–2026-W29
period has 14,818 positive node-weeks out of 812,997 (1.8226%), with all 81
weeks containing at least one revised-domain detection. The candidate positive
fractions are 1.8226%, 1.9158%, 2.0162%, and 2.1120% for W01, W05, W09, and
W13 respectively; the later starts retain fewer weeks and are not preferred
solely for their higher information density.

Mexico contributes 3,124 retained nodes, 44,587 recorded detections,
14,820 positive node-weeks, 1,480 occupied nodes, and 83 weeks with a node
detection. The U.S.-to-40°N portion contributes 6,913 retained nodes and
559,953 possible 2025+ node-weeks, but zero recorded detections, positive
node-weeks, occupied nodes, or detection weeks. It remains in the prospective
domain. The excluded region removes 6,719 nodes, 78,251 detections assigned
to removed canonical cells, and 19,309 positive node-weeks; removed assigned
observations span 2024-01-01 through 2026-07-14 and occur in all 133 audit
weeks.

The 2025+ revised-domain seasonal summary contains 22 winter, 26 spring,
20 summer, and 13 fall weeks, with positive node-weeks of 2,445, 5,294,
4,745, and 2,334 respectively. The observed revised-domain northmost
detection reached 29.24°N by the endpoint; the retained grid extends to
39.9985°N. All candidates support three or four descriptive temporal folds
with 8–13 week validation windows and a 13-week untouched test; a four-fold
13-week validation design plus a 13-week final test leaves 16, 12, 8, or 4
weeks for W01, W05, W09, or W13 respectively.

The recommended response start is **2025-W01**: the first 13 weeks show a
sustained increasing recorded-detection sequence, the full 2025 seasonal
cycle is retained, and the period remains the longest candidate. This choice
uses no predictive model or final-test metric. The complete values and
checksums are in `/project/disease_ecology/STGNN-output/manifests/revised_domain_manifest.json`.

## Implemented rule

The runner retains a canonical cell when its fixed cell center lies in Mexico,
or in the existing canonical U.S. footprint with latitude strictly below
40°N. The geographic mask is then intersected with the already-frozen
canonical environmental-support nodes. No observation locations, convex hull,
buffer, occupancy, livestock missingness, or invasion-front tracing is used to
define the domain.

The revised table retains `canonical_node_id` and adds a contiguous zero-based
`model_node_id`. Its queen graph is the induced subgraph of the original
canonical graph: an edge is retained only when both canonical endpoints are
retained. Components and isolated nodes are reported, not artificially joined.

## Reproducible execution

Run on the Atlas runtime after the Task-2A artifacts are available:

```bash
Rscript scripts/run_revised_domain_audit.R \
  --output-root /project/disease_ecology/STGNN-output \
  --observation-path /project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv \
  --boundary-path /project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg \
  --boundary-layer study_states \
  --git-sha "$(git rev-parse HEAD)"
```

The script reads the frozen canonical nodes, graph, weekly tensors, and static
livestock features. It streams the dynamic arrays while subsetting nodes, so
the source arrays remain unchanged. It writes to:

```text
STGNN-output/revised_domain/{raw,graph,diagnostics,tables,figures,manifests}
STGNN-output/manifests/revised_domain_manifest.json
```

The machine-readable tables include weekly observation summaries,
Mexico/U.S./excluded-region summaries, candidate starts, original-versus-
revised sparsity, latitude-band progression, seasonal coverage, validation
feasibility, and spatial-fold balance. Eight audit figures are generated.

## Response-period decision

The audit compares `2025-W01`, `2025-W05`, `2025-W09`, and `2025-W13` without
fitting a model. The descriptive screening rule selects the earliest candidate
with at least 52 response weeks, at least 75% of its first 13 weeks containing
a revised-domain detection, and no early reporting gap longer than four weeks.
If no candidate passes, `2025-W01` remains the documented full-season default
and the manifest records that the screen did not pass.

This rule is a reporting-continuity screen, not a predictive-performance
criterion. The endpoint remains `2026-W29`; `2026-W30` is excluded.

## Future modeling contract

The proposed contract after review is:

```text
spatial domain: Mexico plus existing U.S. canonical footprint below 40°N
response start: selected by the descriptive candidate-start audit
response end: 2026-W29
environmental history: earlier history retained for optional antecedent features
seasonality: week_sin + week_cos, annual period 52.1775 weeks
recurrent warm-up: not required by default
observation semantics: recorded detection / no recorded detection
```

No hurdle regression, GRU, GConvGRU, XGBoost, spatial model, predictive
comparison, PR-AUC, Brier, NLL, MAE, RMSE, or final-test metric is calculated
by this task.
