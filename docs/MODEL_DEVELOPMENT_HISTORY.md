# STGNN Model Development History

This page records the advancement decisions for the staged revised-domain model
development sequence. Decisions are made from development data only; the sealed
terminal holdout is not used for model selection.

| Task | Model family / scope | Decision | Notes |
| --- | --- | --- | --- |
| 2B | Initial hurdle and GConvGRU development | DO NOT ADVANCE | Initial model family did not meet the advancement requirements. |
| 2C | Metric and spatial audit | DO NOT ADVANCE | Audit and metric validation did not justify advancing the GConvGRU path. |
| 2D | Revised analysis domain and observation-regime audit | Foundation retained | Revised-domain and observation-regime contract established. |
| 2E | Revised-domain hurdle baselines | ADVANCE | Current 24-feature hurdle baseline became the locked reference. |
| 2F | Structured spatial and antecedent augmentations | HOLD / AMBIGUOUS | Augmented models improved average temporal and spatial summaries, but no candidate met every worst-fold and consistency guardrail. Current hurdle remains preferred. |
| 2G | Frozen Hurdle-Current terminal evaluation | PARTIAL GENERALIZATION | Full-domain and Mexico discrimination/Brier skill remain positive, but joint NLL and calibration deteriorate; U.S. transfer is WEAK / AMBIGUOUS. Primary remains Hurdle-Current. |
| 3A | V1 closure and V2 observation/front audit | V1 FROZEN; V2 AUDIT COMPLETE | Observation zeros are strongly structured by prior reporting proximity; causal front states are audit-only. V2-A is recommended next subject to estimand review; V2-D is not identifiable from current data. No V2 predictive model was fit. |
| 3B | V2-A causal front-state hurdle development | V2-A ADVANCES | M1 with 30 predictors and penalty 0.01 improved aggregate historical development performance and first-ever-positive localization; the latitude ablation was REDUNDANT. Folds 5–6 remain historical pseudo-prospective and non-independent. |
| 3C | V2-A frozen development fit and prospective harness | HARNESS READY — AWAITING FUTURE DATA | STGNN-Hurdle-V2A is frozen on 2026-10-03. No post-freeze outcomes were available for independent scoring; forecasts, outcome ingestion, scoring, ledgers, and backfill safeguards are operational. |
| 3D | Delayed prospective nowcast contract and availability-aware front state | HARNESS READY — AWAITING ELIGIBLE NOWCAST WINDOW | Same-week operation is not supported because current-week environmental availability is delayed and historical observation chronology is not a routinely timestamped prospective stream. Availability-causal front history, readiness gating, source/bundle histories, immutable forecasts, and versioned score maturity are operational. No refit or specification change occurred. |
| 3E | V2-A rasterized cell-level outputs and map figures | OUTPUTS COMPLETE — AWAITING INDEPENDENT PROSPECTIVE EVALUATION | Persisted historical pseudo-prospective predictions were reconstructed on the canonical grid for 2026-W17 through 2026-W29, with prediction-only pseudo-nowcast rasters for selected weeks. No refit, model redesign, or independent prospective score was performed. |

Task 2F retains the following decisions for subsequent work:

- keep `Hurdle-Current` as the preferred development model;
- keep the GConvGRU path at `DO NOT ADVANCE`;
- preserve the Task 2G terminal results as historical evaluated data for any future development cycle; and
- preserve the exact 24-predictor Task 2E contract as the reference comparator.

Task 3A initiates a distinct V2 design cycle. Its observation-process and
moving-front diagnostics are descriptive and audit-only. No V2 production
likelihood, response estimand, front-state definition, or future validation
design is authorized by this history entry.

## Current structured A3 milestone

The subsequent structured comparison used the frozen V2-A/A0 30-predictor
reference and four prespecified additions: road density, nighttime illumination,
clay at 0–15 cm, and the WV0033-minus-WV0010 water-retention contrast. With
penalty `0.01`, fixed `theta = 0.7018903965556372`, exact joint hurdle NLL, and
10,037 nodes, A3 improved the F1–F4 development comparison and was frozen as
the current development specification. Neural and graph models were not fitted
in this comparison, feature selection was not reopened, and the main branch was
not merged.

The subsequent evaluation scored the frozen model on the historical exposed
2026-W17–2026-W29 holdout. The result was classified `SUPPORTED` under the
historical rubric, but it is not an independent prospective claim. No eligible
untouched prospective period is currently available.
