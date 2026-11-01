# A5-GNN bounded comparison prespecification

This is a development-only, bounded architecture experiment against the
frozen Structured A3 model. The primary question is whether shallow graph
message passing captures useful residual spatial information beyond A3 and
beyond a spatial-position-only correction.

The only response outcomes eligible for fitting, inner monitoring, candidate
comparison, or decision-making are the original development weeks 2025-W01
through 2026-W16. The four fixed expanding forward folds are F1--F4. W17 and
later outcomes, including W30--W39, are excluded from all A5 development
decisions. No prospective validity claim is made.

## Frozen statistical contract

Every outer fold first reproduces the canonical A3 fixed-theta hurdle fit with
the existing 34 predictors, penalty 0.01, and theta
`0.7018903965556372`. The resulting occurrence and positive-count linear
predictors are frozen offsets. A5 learns only centered residual corrections:

```text
logit(p) = eta_A3 + delta_occ
log(mu)  = xi_A3  + delta_count
```

The loss is the exact observation-level hurdle negative log likelihood: the
Bernoulli term plus the zero-truncated negative-binomial term for positive
counts. No class weighting, focal loss, oversampling, MSE count loss, or
arbitrary task weight is allowed.

## Prespecified candidates

- `A5-PE`: separate node-wise two-layer MLP residual branches using A3
  predictors, A3 offsets, longitude/latitude, and eight graph-Laplacian
  eigenvectors.
- `A5-GNN-NOPE`: separate two-layer mean-aggregation GraphSAGE residual
  branches using A3 predictors and A3 offsets, without positional encodings.
- `A5-GNN`: the primary model, with the same inputs as A5-PE and two-layer
  mean-aggregation GraphSAGE residual branches.

Both branches have hidden dimension 16, ReLU activation, dropout 0.10,
AdamW learning rate `1e-3`, weight decay `1e-4`, and gradient clipping at 1.0.
The residual is centered across nodes independently for each week and branch
before being added to the A3 offset. There is no architecture or width/depth
sweep.

Exactly three seeds (`1729`, `31415`, and `271828`) are applied to every A5
variant. An inner terminal training block is used only to choose training
duration. The selected epoch count is then refit on the complete outer
training fold before the untouched validation fold is scored once.

## Leakage controls

Message passing receives only the 34 causal A3 predictor values, frozen A3
offsets, and fixed response-independent positional information. Neighboring
target-week outcomes, residuals, validation outcomes, and future outcomes are
never passed to the model. The runner writes explicit feature/target access
audits and executes mutation-based leakage tests.

## Decision rule

The runner reports exactly one primary decision label from the four labels in
the task specification. The result is development evidence only. Even a
development-supported challenger would require a separately frozen artifact
and independent post-freeze validation before any operational use.

## Execution storage and recovery

Regenerable checkpoints, predictions, tensors, caches, and logs are written to
`/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/` and are
recorded as `TEMPORARY_90DAY_STORAGE`; inactive data are automatically removed
after 90 days. Compact metrics, provenance, figures, and the final report are
promoted to the durable project analysis tree only after successful completion.
Atomic candidate/fold/seed checkpoints are reused only when their execution
SHA, configuration hash, input hashes, graph contract, and completion marker
match the current run.

The A5-GNN result is interpreted separately as predictive performance,
residual spatial structure, and mechanistic meaning. A Moran reduction is
treated as evidence of additional spatially structured predictive information,
not as evidence of causal transmission, latent abundance, surveillance-effort
correction, dispersal parameters, or intervention effects.
