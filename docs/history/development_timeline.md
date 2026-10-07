# Development timeline

1. Initial STGNN / GConvGRU experiments — [GConvGRU architecture](GCONVGRU_ARCHITECTURE.md).
2. Canonical grid/domain development — [domain audit](REVISED_DOMAIN_AUDIT.md).
3. Revised Mexico + southern U.S. domain — [domain decision](modeling_decisions/001_domain_revision.md).
4. Structured V2-A model — [V2-A model selection](TASK3B_V2A_MODEL_SELECTION.md).
5. Soil feature screening — [soil decision](modeling_decisions/003_soil_feature_screening.md).
6. Road / nighttime illumination augmentation — [augmentation decision](modeling_decisions/004_controlled_predictor_augmentation.md).
7. Structured A3 selection — [A3 decision](modeling_decisions/006_structured_a3_selection.md).
8. Neural/GNN architecture audit — [neural-model decision](modeling_decisions/005_neural_model_evaluation.md).
9. Neural model class not supported — [model development history](MODEL_DEVELOPMENT_HISTORY.md).
10. Structured A3 frozen — [development milestone](milestones/structured_a3_development_milestone.md).
11. Historical exposed holdout — [holdout decision](modeling_decisions/007_historical_holdout_evaluation.md).
12. Full-fit spatial products and interpretation — retained analysis artifacts under `analysis/structured_a3_fullfit/`.
13. Current research release — release documentation under [`../release/`](../release/).

The repository was originally named `STGNN` during evaluation of graph-neural-
network approaches. After formal model-class evaluation supported the
Structured A3 statistical machine-learning framework instead, the project was
renamed `hominivorax-ml`.
