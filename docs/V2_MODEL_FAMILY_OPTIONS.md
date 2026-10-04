# V2 model-family options

## Decision status

Task 3A does not fit or select a V2 production model. The following ranking is
a design recommendation under SAE and requires explicit review of the V2
response estimand before implementation.

| Family | Status | Rationale |
| --- | --- | --- |
| V2-A | **RECOMMENDED NEXT** | Strong prior-distance and front-history structure is present. It is the smallest extension of the recorded-detection hurdle benchmark and can retain positive-count modeling. |
| V2-B | **PLAUSIBLE SECONDARY** | Addresses unequal zero-label interpretation through a background design, but changes the occurrence estimand and requires defensible background sampling. |
| V2-C | **DEFER** | A recorded-detection intensity model is conceptually natural for counts and repeat reports, but should follow the observation/front audit and a clear interpretation of `lambda`. |
| V2-D | **NOT IDENTIFIABLE** | Current data lack an observation denominator, effort process, repeated negatives, known-at-risk units, or validated reporting proxies needed to separate latent occurrence from detection. |

## V2-A — current hurdle plus causal front state

V2-A would retain the V1 recorded-detection response while adding a frozen,
strictly causal set of front descriptors. Candidate variables include prior-set
distance, time since nearby detection, and one or more stable percentile-front
summaries. It is computationally feasible on Atlas, interpretable, preserves
weekly grid predictions, and directly tests the front hypothesis. Its limitation
is that it does not solve passive-reporting confounding; its estimand remains
recorded detection.

## V2-B — presence-background occurrence plus conditional count

V2-B would define positive node-weeks as events and compare them with a stated
background design. The audit compared: all available domain node-weeks;
temporally matched random nonpositive node-weeks; and temporally matched
region/5-degree-latitude-matched nonpositive node-weeks. The samples are
descriptive only. A background design changes the occurrence estimand and must
not be presented as an unbiased correction without review.

## V2-C — recorded-detection intensity

V2-C could model node-week count intensity directly with Poisson or negative
binomial likelihood, seasonal terms, environmental predictors, static hosts,
causal front state, and possibly spatial effects. It is compatible with repeat
reports and avoids forcing the count process through a binary hurdle, but
`lambda` must be interpreted as recorded-detection intensity, not true
abundance or latent occurrence.

## V2-D — latent occurrence plus observation process

V2-D is scientifically attractive but not identifiable from the current data
alone. A separate observation component would require effort, repeated negative
surveys, known-at-risk units, or credible reporting proxies with sufficient
spatiotemporal coverage. Administrative state, broad region, host category, and
coordinates are not adequate substitutes.

## Recommendation

Proceed first with a reviewed V2-A estimand and validation design, using the
audit-only front descriptors as candidates rather than silently freezing them.
Retain V2-B as a secondary sensitivity direction if the project authorizes a
presence-background estimand. Defer V2-C until the count-versus-zero decision
is reviewed, and do not pursue V2-D without new information supporting
observation-process identifiability.

No GRU, GConvGRU, hurdle-front model, background classifier, point-process
model, or latent observation model was fitted in Task 3A.
