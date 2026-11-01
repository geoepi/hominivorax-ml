# A5B Multiscale Component-Specific Spatial ML report

## I. Governance

This is a supervised-agent `DEVELOPMENT_INFORMED_FOLLOWUP` under SAE governance. The A3 production artifact, frozen A4-S artifact, completed A5 result, and production configuration were treated as immutable. No merge, release, or production change was made.

## II. Starting state

A5 parent SHA: `e71c02c3ea87a4ab13dbb7733277c17b9c53c550`. A5B execution SHA: `51c08cc8531aae290e7b778d543249475c2a9bb0`. Branch: `feature/a5b-multiscale-component-spatial-ml`. Prior A5 decision preserved as `A5_GNN_NOT_SUPPORTED`. A3 SHA: `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`. A4-S manifest SHA: `156ab650b8fa79f7a4fe390f3687ca53212fbf37fb7e9963ba91b9f70c9b68af`. Canonical graph SHA: `539876a1528c84f2bf7ab97f5b8f20b3da480cb1c705ac47611542e4a00ad9a7`.

## III. A5 evidence motivating A5B

A5 showed improved discrimination without sufficient residual spatial correction. The prespecified motivation was A3 first-shell occurrence residual Moran's I 0.293260 versus 0.245346 for A5-GNN-NOPE, an approximate 0.0479 reduction that narrowly missed the 0.05 guardrail, with larger-shell weakening and no useful positive-count correction. A5B therefore removes positional encodings and targets occurrence with exact multiscale shell relations.

## IV. Atlas storage configuration

`/project/disease_ecology`: {'path': '/project/disease_ecology', 'total_bytes': 5500000272384, 'used_bytes': 4957577150464, 'free_bytes': 542423121920}. `/90daydata/disease_ecology` run root: `/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_20261102T030000Z_51c08cc`. Cache: `/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_20261102T030000Z_51c08cc/cache`. TMPDIR: `/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_20261102T030000Z_51c08cc/tmp`. Slurm logs: `/90daydata/disease_ecology/hominivorax-ml/a5b_multiscale_component_spatial_ml/run_20261102T030000Z_51c08cc/logs`. Durable summaries: `/project/disease_ecology/STGNN-output/_WORKTREES/a5b-multiscale-component-spatial-ml/analysis/a5b_multiscale_component_spatial_ml`. Large runtime products are labeled `TEMPORARY_90DAY_STORAGE` and are subject to automatic deletion after 90 days without activity.

## V. Multiscale graph construction

The canonical 10,037-node, 77,614-directed-edge queen graph was the only primitive topology. Exact deterministic shortest-path shells 1--4 were constructed in canonical node order; shell pair counts and SHA-256 hashes are in `results/spatial_shell_contract.csv`. Learned adjacency, outcome-derived edges, and explicit self-loops were not used. Shell counts: `{'1': {'pair_count': 77614, 'sha256': 'aa709b2cae3239a8e98072a92f988c7079ebe7c389931d0a71c6aa0383822801'}, '2': {'pair_count': 150880, 'sha256': '8054a77175c3ff20480f6121589396fe40497a82c68abe0ecec0ef5491d4b8be'}, '3': {'pair_count': 220116, 'sha256': '52af6540c1989ad025749fde1c594665b28403b741340a4f54460b2ed719cc79'}, '4': {'pair_count': 285662, 'sha256': '1db445c03c69e302bc9b14f5d64326e6b650b1201d6f32b3cf73c37cfa823b90'}}`.

## VI. A5B architecture

A5B-MS-OCC is a shallow four-relation mean GraphSAGE occurrence residual model. Each shell has a separate operator with hidden width 8; the four representations are concatenated, passed through a ReLU/dropout 0.10 head, and mapped to one centered occurrence correction. Inputs are standardized 34 A3 predictors plus the A3 occurrence and positive-count linear predictors. No coordinates, eigenvectors, free node embeddings, attention, recurrence, or graph search were used.

## VII. Leakage verification

The target-week outcome is used only in the occurrence-component training loss and post-prediction metrics; it is never passed as a node feature or edge. Shells are built only from the response-independent canonical edge artifact. No validation or future outcome, residual, intervention/SIT variable, or post-2026-W16 outcome entered architecture or graph selection. Per-week residual centering is across eligible training nodes.

## VIII. Predictive performance

A3 mean PR-AUC `0.4741350569159318`, Brier skill `0.3706793895704873`, joint hurdle NLL `0.0763332900086996`. A5-GNN-NOPE mean PR-AUC `0.5094554321315202`, Brier skill `0.3706867128060365`, joint hurdle NLL `0.0757656507646329`. A5B-MS-OCC mean PR-AUC `0.5125939396620243`, joint hurdle NLL `0.0762969342748437`. A5B-HYBRID mean PR-AUC `0.5125939396620243`, joint hurdle NLL `0.07408535905728243`. Complete fold/seed metrics are in `results/fold_seed_metrics.csv`.

## IX. Occurrence spatial residuals

The primary shell-1 reduction and shells 2--4 preservation assessment is `no candidate satisfied the provisional decision logic`. A5B occurrence Moran's I is reported for all four shells alongside A3 and A5-GNN-NOPE in `results/residual_spatial_summary.csv`. Improvement beyond A3: `False`; improvement beyond A5-GNN-NOPE at larger shells: `False`.

## X. Positive-count spatial residuals

A5B-MS-OCC retains A3's positive-count component. A5B-HYBRID uses the immutable A4-S `count_beta` and `count_spatial_effect` arrays without refitting; maximum conditional/mu reproduction differences are in `results/hybrid_count_reproduction.csv`. Frozen A4-S artifact hashes are `05dcb211d4bacb24dd4ef9399aa2e495ff85c1121439a40c32a3a05d09de4373` and `eef5fadc614c543dada56ace20104ee0f9aca49cc88321c43f9c8e4d9f40c6ca`. No claim is made that the occurrence network solves positive-count spatial dependence.

## XI. Full-hurdle residuals

Full-hurdle expected-count residual Moran's I at shells 1--4 is reported separately from occurrence and positive-count residuals in `results/residual_spatial_summary.csv`.

## XII. Temporal residuals

Same-cell residual correlations at lags 1, 2, and 3 weeks are reported for occurrence, positive count, and full hurdle count in `results/residual_temporal_summary.csv`. A5B is non-recurrent; temporal dependence is documented rather than modeled away.

## XIII. Spatial stress test

Stress status: `{'status': 'COMPLETED', 'spatial_fold_count': 5, 'selection_used': False, 'a4s_refit': False, 'reference_stress_source': 'completed_a5_compact_artifact'}`. The existing deterministic spatial partition was reused unchanged, held-out outcomes were excluded from training, and stress results were excluded from model selection. A4-S was not refit.

## XIV. Frontier performance

Previously unoccupied cells, recent occupancy, distance-to-prior-detection classes, and first-recorded-detection events where estimable reuse the completed A5 definitions. Results are in `results/frontier_metrics.csv`; intervention-confounded U.S. raw count magnitude was not used as a selection endpoint.

## XV. Seed stability

Seeds 1729, 31415, and 271828 were used. Seed-level PR-AUC and Moran summaries are retained; the selected-candidate stability assessment is `not applicable`.

## XVI. Component-specific hybrid assessment

The frozen A4-S NPZ permitted exact extraction of the positive-count component without refit. Hybrid count reproduction passed: `True`. The component-specific evidence supports different occurrence and positive-count spatial treatments: `True`.

## XVII. Limitations

A5B was designed after inspecting F1--F4 A5 results and is not independent validation. It cannot establish prospective superiority, causal transmission, dispersal, surveillance effects, intervention effects, or biological mechanism. The frozen A4-S full-development artifact is a fixed reference component; later independent evaluation remains required.

## XVIII. Primary decision

`A5B_NOT_JUSTIFIED`. This means only that the specified architecture is or is not sufficiently promising for a later independent-validation freeze decision; it does not authorize deployment.

## XIX. Repository/PR state

Branch: `feature/a5b-multiscale-component-spatial-ml`. Parent A5 history was not rewritten. A3, A4-S, and A5 artifacts remain unchanged. No merge or release was performed. Focused tests and Atlas execution evidence are recorded in provenance.

## XX. Storage/artifact state

`DURABLE_PROJECT_ARTIFACTS`: compact CSV/JSON summaries, figure-source tables, provenance, checksums, and this report under the A5B project worktree. `TEMPORARY_90DAY_STORAGE_ARTIFACTS`: checkpoints, predictions, training traces, residual maps, spatial tensors, caches, temporary figures, and Slurm logs under the run-specific `/90daydata` root. The latter are automatically deleted after 90 days of inactivity. A provisional candidate does not automatically promote large model state; any future freeze requires a separate storage/freeze decision.

Figure status: `{'status': 'FIGURE_RENDERING_DEFERRED_ENVIRONMENT_LIMITATION', 'figure_source_tables': 'generated', 'reason': 'matplotlib unavailable in supported Atlas environment'}`. Figure-source tables were generated regardless of graphics availability.
