# STGNN-Hurdle-V2A Delayed Prospective Nowcast Contract

## Status

`STGNN-Hurdle-V2A` is a development-frozen 30-feature hurdle model. Task 3D
changes its operational chronology only; it does not refit or redesign the
statistical specification. The authorized operational use is a **delayed
prospective nowcast** for a historical week, not a same-week forecast.

## Why same-week forecasting is not supported

The current-week environmental bundle is normally available approximately one
to two weeks after the represented week. Observation files may also lag by
several weeks. Consequently a week-*t* prediction cannot be described as a
same-week or real-time forecast when the week-*t* predictors are not available
before the end of week *t*.

A delayed nowcast for week *t* is issued after a complete week-*t* environmental
bundle is verified but before week-*t* outcomes are available to the STGNN
workflow. If that interval cannot be established, the run is not independent
prospective evidence.

## Eligibility rule

A production nowcast is `prospective_eligible` only when all of the following
hold:

1. all 12 current-week environmental predictors are complete and verified;
2. the forecast artifact is frozen and checksummed;
3. no week-*t* outcome is known to the workflow before issue time;
4. the frozen model-manifest checksum matches; and
5. the front state uses `history_mode=availability_causal`.

Other outcomes are labeled `retrospective_only`, `environment_not_available`,
`outcome_already_available`, or `availability_uncertain` and are excluded from
genuine prospective metrics.

## Event date versus availability date

An observation's event week describes when the detection occurred. It does not
establish when the record became available to the model. When row-level report
timestamps are unavailable, the earliest source-version timestamp at which the
row is known to exist is recorded as `observed_first_available_timestamp`.
This is a conservative availability proxy, not a report date.

## Availability-causal front state

The frozen feature definitions are unchanged. For a nowcast issued at time
*T*, prior detections may enter the front state only when both conditions hold:

```text
event_week < forecast_week
and observed_first_available_timestamp < T
```

Thus late historical backfills cannot revise an already issued forecast. The
historical `event_causal` mode remains available for reproducible sandbox tests;
production nowcasts default to `availability_causal`.

## Immutability and score versioning

The pre-outcome prediction parquet and its checksum are immutable. Outcome
artifacts and scores are versioned because observation data can mature. A score
is marked `provisional` or `mature`; a later score version may supersede the
reported score while leaving the original forecast unchanged.

The first genuinely eligible nowcast had not been identified at the start of
Task 3D because the available source already contained the historical W29
outcomes and environmental availability timestamps were not verified. The
harness therefore remains **HARNESS READY — AWAITING ELIGIBLE NOWCAST WINDOW**.

