# Frozen STRUCTURED A3 evaluation

This directory is the evaluation-only workstream for the frozen STRUCTURED A3
model. It does not change the model specification, fit a neural or graph model,
reopen feature selection, recalibrate probabilities, or merge to `main`.

The immutable pre-evaluation manifest is
`results/frozen_a3_evaluation_manifest.json` and its checksum is recorded in
`results/frozen_a3_evaluation_manifest.json.sha256`. The historical/prospective
evaluation could not be executed in the available workspace because the
authoritative protected production bundle, response source, and static A3
augmentation artifacts were not present. Required outputs therefore contain
explicit stop statuses and no fabricated metrics.

When the authorized data bundle is available, run the preflight first:

```text
python analysis/structured_a3_evaluation/scripts/preflight_frozen_a3_evaluation.py
```

The preflight is deliberately outcome-blind: it checks paths, manifests, and
metadata only. Scoring must not begin unless it verifies the frozen A3 manifest,
causal history support, frozen scaling support, and complete predictor coverage.

The existing frozen development implementation is retained under
`analysis/predictor_augmentation/`; it is imported as provenance and is not
modified by this evaluation workstream.
