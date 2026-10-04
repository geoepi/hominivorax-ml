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

Task 2F retains the following decisions for subsequent work:

- keep `Hurdle-Current` as the preferred development model;
- keep the GConvGRU path at `DO NOT ADVANCE`;
- preserve the Task 2G terminal results as previously seen data for any future development cycle; and
- preserve the exact 24-predictor Task 2E contract as the reference comparator.
