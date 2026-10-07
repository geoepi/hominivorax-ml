# Task 2B recurrent architecture

The primary model is `GConvGRU-Hurdle-NB`. Its input width is 24:

* 12 weekly environmental predictors;
* five completed livestock density surfaces, transformed with `log1p` inside
  each fold's preprocessing;
* five 0/1 livestock-imputation indicators, left unscaled;
* `week_sin` and `week_cos`, left on their natural range.

Coordinates, node identifiers, response lags, rolling response summaries, and
future information are excluded from the primary input. The spatial domain is
the fixed 16,756-node Task-1 environmental intersection. The persisted binary,
undirected queen graph is consumed unchanged: 128,684 directed edges, 31
components, and 17 isolated nodes.

The full graph is processed at every time step. The initial recurrent layer is
one PyG Temporal `GConvGRU`, with a staged search over hidden width 32/64/128
and Chebyshev `K` 2/3. The approved initial normalization is symmetric
graph-Laplacian normalization (`normalization="sym"`); persisted edges remain
unchanged and uniform edge weights of one are supplied only when the API
requires them. No learned, distance-weighted, directed, or attention edges are
introduced.

The matched `GRU-Hurdle-NB` comparator uses the same 24 inputs, hidden width,
activation, dropout, heads, global dispersion, loss, and training schedule, but
has shared node-wise GRU parameters and no neighbor message passing.

Each fold begins with 52 weeks of environmental warm-up. Warm-up predictors
initialize hidden state but have no response loss and no pre-2024 response
values are supplied. Training uses contiguous 13-week truncated-BPTT chunks,
retaining and detaching hidden state between chunks. Gradient norm is clipped
at 1.0. Fold-specific scaling is persisted separately from the raw Task-2A
arrays.

Validation is development-only. Temporal, spatial, and combined masks are
read from the Task-2A split artifacts. Held-out spatial nodes remain in the
known transductive graph and retain predictors, but their response targets are
excluded from fitting. The final-test guard rejects predictive scoring in the
default `evaluation_mode: development` configuration.

## Atlas execution evidence

The validated Atlas Python stack was Python 3.12.14, PyTorch 2.10.0 with CUDA
12.8, PyG 2.8.0.post1, and torch-geometric-temporal 0.54.0. The GPU smoke and
development runs used the A100-capable Atlas partitions; the mixed-precision
smoke ran on an NVIDIA A100-SXM4-80GB MIG 1g.10gb slice. The complete finalist
comparison uses five fixed seeds across all four temporal folds. Checkpoints,
run manifests, and metrics are outside Git under the Task-2B output root.
