# Model Qualification Summary

This entry point summarizes the completed qualification program for the
original W16-frozen `STRUCTURED_A3` candidate. Those P1–P7 results are tied to
that immutable model and do not qualify the later W44 candidate. The W44 Q1
retrospective replay completed, but target maturity was uncertified and its
scientific qualification decision is `NOT_ASSIGNED`; independent prospective
qualification remains pending. See [current model status](current/status.md)
and the [W44 model-development decisions](current/model_development_decisions.md).

Frozen model artifact SHA-256: `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`

| Phase | Objective | Decision | Major finding | Canonical report |
|---|---|---|---|---|
| P1 | Transfer validation | `P1_TRANSFER_VALIDATION_SUPPORTED_WITH_LIMITATIONS` | Transfer and frontier limitations remain explicit. | [`P1 report`](../analysis/p1_production_validation/p1_validation_report.md) |
| P2 | Rolling-origin 1--3 week nowcast evaluation | `P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS` | Occurrence performance and count behavior are characterized by horizon. | [`P2 report`](../analysis/p2_operational_nowcast/p2_operational_nowcast_report.md) |
| P3 | Bounded robustness | `P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS` | Main conclusions are stable within bounded sensitivity designs, with sparse frontier/regional support. | [`P3 report`](../analysis/p3_robustness/p3_robustness_report.md) |
| P4 | Uncertainty and support | `P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS` | Support and extrapolation are quantified and emitted as flags. | [`P4 report`](../analysis/p4_uncertainty_extrapolation/p4_uncertainty_extrapolation_report.md) |
| P5 | Operational contract | `P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED` | Retrospective environmental inputs were not prospective without a proxy. | [`P5 report`](../analysis/p5_operational_contract/p5_operational_contract_report.md) |
| P5A | Issue-time proxy validation | `P5A_ENVIRONMENTAL_PROXY_SUPPORTED` | E0_LAST_AVAILABLE provides a validated prospective proxy with limitations. | [`P5A report`](../analysis/p5a_environmental_proxy/p5a_environmental_proxy_report.md) |
| P6 | Production hardening | `P6_PRODUCTION_HARDENING_SUPPORTED_WITH_LIMITATIONS` | Deterministic, restartable operation is documented with tooling/source-vintage limitations. | [`P6 report`](../analysis/p6_production_hardening/p6_production_hardening_report.md) |

## Qualified use

Use is limited to short-horizon nowcasting under the E0_LAST_AVAILABLE issue-time
environmental-context rule. Support classes and uncertainty fields must accompany
predictions. Frontier and regional support, count bias, extrapolative support,
proxy dependence, and causal-interpretation limitations remain active.
