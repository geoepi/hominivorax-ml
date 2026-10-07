# V2 validation strategy audit

## Data-status principle

The V1 terminal period 2026-W17–W29 is historical evaluated data. It may be
used in a future V2 development analysis only when explicitly labeled as such;
it cannot be called an independent holdout or final test again. No V2 choice in
Task 3A was optimized against V1 terminal Brier, PR-AUC, U.S. ranks, or joint
NLL.

## Candidate strategies

| Strategy | Role | Feasibility | Strength | Limitation | Recommended use |
| --- | --- | --- | --- | --- | --- |
| A. Rolling-origin | Development validation | High | Tests multiple temporal origins and causal feature availability | Reuses already inspected 2025–2026 outcomes | Primary V2 development check |
| B. Leave-late-period-out pseudo-prospective folds | Historical pseudo-prospective evaluation | High | Tests frozen specifications on late historical periods | Not independent; cannot be called final test | Secondary development evidence |
| C. Geographic transfer folds | Transfer diagnostic | Moderate | Directly probes south-to-north and Mexico-to-U.S. transfer | Few U.S. positives and geographic imbalance | Pre-specified diagnostic |
| D. Future accumulating unseen data | Genuine future evaluation | Requires future data | Preserves independence after V2 freeze | Requires waiting and a written freeze protocol | Preferred long-term final evaluation |

The machine-readable comparison is
`tables/validation_strategy_comparison.csv`.

## Recommended design

For V2 development, use rolling-origin folds with front descriptors constructed
strictly within each fold and geographic-transfer diagnostics reported
separately. Add leave-late-period-out pseudo-prospective summaries as historical
evidence, explicitly labeled non-independent. Once the V2 estimand, front-state
definition, background design if applicable, and likelihood are frozen, reserve
newly arriving observations for the first genuinely unseen evaluation.

The former V1 terminal observations should not be rebranded as that future test.
If no new observations accumulate, the project should report that an independent
test is unavailable rather than manufacture independence from previously
inspected data.

## Leakage requirements for future V2 work

Every fold must construct front history using weeks strictly earlier than the
prediction week and must apply the same rule inside training and validation
periods. Required tests include future-data mutation invariance, current-week
response invariance, node/week ordering, reproducible background sampling, and
manifest consistency. No threshold, front-distance cutoff, risk threshold, or
background ratio should be tuned against a historical evaluated period.

## Validation conclusion

The recommended long-term design is: rolling-origin development validation plus
pre-specified geographic transfer diagnostics, followed by a genuinely unseen
future accumulation after the V2 specification freeze. This separates
development validation, historical pseudo-prospective evaluation, and future
unseen evaluation without overstating independence.
