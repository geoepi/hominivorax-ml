# Current model and repository status

**Status date:** 2026-11-22. This is the canonical current-status record; the
README and `MODEL_STATUS.md` link here for detail.

**Supported architecture:** `STRUCTURED_A3`, the frozen 34-predictor
spatiotemporal hurdle specification. **Original scientific training cutoff:**
2026-W16. The W16 freeze and its development history remain unchanged.

**Candidate status:** `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.

| Record | Date and horizon | Model identity | Artifact root | Qualification / operational state |
|---|---|---|---|---|
| Original frozen scientific specification | Frozen 2026-10-06; fit 2025-W01–2026-W16 | `STRUCTURED_A3`; frozen metadata/coefficients SHA-256 `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e` | `config/production_model_freeze.json`; `analysis/structured_a3_evaluation/results/final_a3_model.json` | Specification frozen; original P0 identity retained |
| Previously active production artifact | W29 full fit; isolation last documented 2026-11-19 | `STRUCTURED_A3` W29 full fit; model SHA-256 begins `1cb694f`; active configuration SHA-256 begins `f51038` | Atlas `/project/disease_ecology/STGNN-output/structured_a3_fullfit`; deployed manifest under `/project/disease_ecology/STGNN-production/deployment_manifest.yaml` | Remains the active production artifact according to the 2026-11-19 isolation record; this repository does not establish the deployed release tag |
| Latest completed candidate full fit | Fit completed 2026-11-19; training 2025-W01–2026-W44 | `STRUCTURED_A3_2026W44`; model SHA-256 `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b` | Atlas `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44`; aggregate identity and provenance in `analysis/structured_a3_data_refresh_2026w44/` | `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`; not promoted |
| W44 Q1 retrospective evaluation | Completed 2026-11-21; 26 origin fits and 78 horizon blocks | W44 candidate; E0 primary and E1 sensitivity; 2,348,658 row predictions | Repository aggregates in `analysis/structured_a3_data_refresh_2026w44/qualification_execution/results/2026w44_q1_retrospective/`; row-level archive remains on Atlas at `/project/disease_ecology/STGNN-output/structured_a3_2026w44_q1_retrospective_attempt02/` | `COMPLETED`; target maturity is uncertified, scoring eligibility is limited, and scientific qualification decision is `NOT_ASSIGNED` |
| Independent prospective qualification of the fixed W44 candidate | Not yet executed; requires eligible post-issue origins and mature outcomes | `STRUCTURED_A3_2026W44` fixed candidate | No prospective result root exists | Pending; no prospective qualification or production decision is claimed |

The W44 observation source contains 164,767 records through W46. The W44
candidate used the accepted source checksum shown above and excluded W45–W46
from its training horizon. The missing reporting-completeness certificate and
unexplained historical revisions remain limitations. The historical Q1
replay uses revised-vintage outcomes and cannot establish prospective
qualification.

## Scientific findings and limitations

- The A3 development comparison advanced and the `STRUCTURED A3 DEVELOPMENT
  SPECIFICATION FROZEN` disposition remains the supported architecture.
- A4, A5, A5B, and evaluated A6 alternatives were not selected. Their evidence
  and exact decision codes are in the [model-development decision
  register](model_development_decisions.md).
- The completed point-level investigation decision is
  `POINT_PROXIMITY_CHALLENGER_NOT_JUSTIFIED`. The descriptive same-week
  nearest-neighbour median was approximately 1.45 km; opportunistic reporting
  limits interpretation, and the tested history features were redundant with
  the frozen A3 predictors.
- Residual spatial correlation remains a diagnostic and scientific limitation.
  It is not a new pass/fail requirement to eliminate spatial autocorrelation.
- Predictions describe recorded reports, not organism abundance. Issue-time
  environmental availability, outcome maturity, frontier support, and
  historical data revisions limit transfer claims.

## Execution pathways

The P6 operational inference command, P0–P5 descriptive full-fit pipeline,
and W44 development candidate-refresh workflow have different purposes and
output roots. Their contracts are documented in the
[production entrypoint inventory](../release/production_entrypoint_inventory.md).
The proposed separation of routine data refresh and performance monitoring
is recorded in [routine model refresh](routine_model_refresh.md); it is not
approved policy and does not change existing qualification requirements.
