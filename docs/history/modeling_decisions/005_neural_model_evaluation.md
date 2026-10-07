# 005 — Neural and graph model evaluation

## Question

Do neural, recurrent, or graph-convolutional model classes meet the current probabilistic validity and reproducibility requirements?

## Decision

Do not advance neural/GConvGRU or graph model classes as the current production-development path.

## Evidence

The model-class diagnostic, neural A0 architecture audit, and STGNN A3 ablation branches preserve architecture, loss, convergence, calibration, and training-behavior diagnostics. These workstreams did not provide a supported replacement for the structured hurdle protocol.

## Rejected alternatives

Reopening feed-forward, GRU, GConvGRU, or graph-specific selection is not justified by the current milestone and would violate the frozen A3 scope.

## Provenance and status

Relevant tips: `844589d`, `45dd7fe`, local/remote A3-ablation tips `fc7c17d`/`4797edf`. Status: **historical evidence; branches retained**.
