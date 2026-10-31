# Controlled Results Synthesis

This document is generated from canonical P1--P7G machine-readable artifacts. It is a controlled source for manuscript wording, not a new scientific analysis.

## Qualified model and horizon

The frozen model is `STRUCTURED_A3` with 34 predictors on the 25 x 25 km canonical grid (10037 cells). The qualified operational configuration uses `E0_LAST_AVAILABLE` across the 1--3 week nowcast horizon.
Source: `config/production_model_freeze.json`; `config/p6_production_config.json`.

## Canonical decisions

P1: `P1_TRANSFER_VALIDATION_SUPPORTED_WITH_LIMITATIONS`
P2: `P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS`
P3: `P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS`
P4: `P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS`
P5: `P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED`
P5A: `P5A_ENVIRONMENTAL_PROXY_SUPPORTED`
P6: `P6_PRODUCTION_HARDENING_SUPPORTED_WITH_LIMITATIONS`
P7G: `P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS`

## P7G evidence

P7G residual dependence diagnostics show reduced but nonzero spatial and temporal association after fitted-mean subtraction. At h=1, occurrence shell-1 values were raw=0.6774 and residual=0.3630; pooled lag-1 values were raw=0.4778 and residual=0.1535. Source: P7G spatial and temporal dependence tables.
P7G first-recorded detection ranking captured 84.0%, 79.7% and 74.7% of frontier-relative events in the top 5% at h=1--3, respectively. Source: P7G early-warning table.
P7G predictor-dependence counts were 19 at absolute Pearson correlation >=0.70 and 11 at >=0.90. Standardized associations are conditional, scale-labeled point estimates; coefficient-bootstrap stability intervals were not available.
P7G support-stratified Brier scores were 0.0088, 0.0080, 0.0072 for SUPPORTED rows and 0.0513, 0.0510, 0.0505 for EXTRAPOLATIVE rows across h=1--3. Source: P7G support calibration tables.

## Existing qualified results

P2 occurrence, P5A proxy, frontier, count, support, and P6 production claims remain unchanged and are sourced from the existing P7 table/claim artifacts. These are retrospective or contract-validation results with the limitations recorded in P1--P7G.
