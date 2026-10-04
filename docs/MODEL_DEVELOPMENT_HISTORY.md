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

Task 2F retains the following decisions for subsequent work:

- keep `Hurdle-Current` as the preferred development model;
- keep the GConvGRU path at `DO NOT ADVANCE`;
- preserve the Task 2G terminal results as historical evaluated data for any future development cycle; and
- preserve the exact 24-predictor Task 2E contract as the reference comparator.

Task 3A initiates a distinct V2 design cycle. Its observation-process and
moving-front diagnostics are descriptive and audit-only. No V2 production
likelihood, response estimand, front-state definition, or future validation
design is authorized by this history entry.
| 3B | V2-A causal front-state hurdle development | V2-A ADVANCES | Historical rolling-origin development; latitude ablation LATITUDE REDUNDANT; no unseen V2 test. |
