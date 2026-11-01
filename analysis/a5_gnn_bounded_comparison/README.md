# A5-GNN bounded spatial challenger

This directory contains the reproducible development comparison specified in
`prespecification.md`. It does not alter the frozen `STRUCTURED_A3` model,
the frozen `STRUCTURED_A4S_CHALLENGER`, production configuration, or
production outputs.

The Atlas entry point is:

```text
hpc/run_a5_gnn_bounded_comparison.sbatch
```

Large checkpoints and prediction arrays are written to the authorized Atlas
`/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/` output
root. The output root is explicit through `--output-root` or
`A5_GNN_OUTPUT_ROOT`; caches and `TMPDIR` are redirected under the same
temporary root. Only compact metrics, diagnostics, manifests, figures, and the
final report are promoted to the durable project analysis tree after successful
completion.

Large execution products are labeled `TEMPORARY_90DAY_STORAGE` and are
automatically removed after 90 days without activity. Each candidate/fold/seed
unit has an atomic checkpoint with the execution SHA, configuration hash,
input/graph provenance, and completion status. Only provenance-matching,
completed checkpoints are reused after an interruption.

The primary results use only F1--F4 over 2025-W01--2026-W16. The experiment
uses three fixed seeds for each A5 candidate, exact fixed-theta hurdle loss,
the canonical 10,037-node queen graph, and response-independent positional
encodings. The secondary spatial-block stress test reuses the repository's
existing deterministic spatial partition when the persisted assignment is
available; it is descriptive and is never used for tuning or ranking.

## A5 versus prior GConvGRU/STGNN work

The rejected prior pathway was a high-capacity recurrent GConvGRU/STGNN
reconnaissance model on the earlier 24-predictor contract. It learned the
response heads directly, used recurrent hidden state, and historically showed
severe probability overprediction and negative Brier skill. A5 is materially
different: it freezes the current 34-predictor A3 systematic component and
learns only a shallow, centered residual correction with separate occurrence
and positive-count branches. It is non-recurrent, uses a fixed graph and
response-independent positional encodings, and is trained with the exact
joint hurdle likelihood and fixed A3 dispersion. A5-PE and A5-GNN-NOPE are
prespecified controls for positional information and graph message passing.
