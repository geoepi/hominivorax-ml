# Contributing

## Bugs

Open a bug report with the smallest reproducible example, relevant input
schema, software environment, and failing test or log excerpt. Do not attach
protected observations, credentials, or Atlas-local production artifacts.

## Scientific/model questions

Use the scientific/model-question issue template. Describe the estimand,
response definition, predictor contract, evaluation period, and whether the
question concerns the frozen production model or an experimental branch.

Consult [`docs/current/status.md`](docs/current/status.md) before using or
describing a model artifact. The W44 candidate and its Q1 retrospective results
are not production-qualified. The completed A4–A6 and point-proximity decisions
are recorded in [`docs/current/model_development_decisions.md`](docs/current/model_development_decisions.md);
no new architectural challenger or point-pattern experiment is authorized by
the current maintenance scope.

## Scientific changes

Structured A3 is frozen. Any change to predictors, transformations, response,
theta, penalty, objective, domain, or validation protocol requires an explicit
scientific evaluation and updated provenance before it can be considered for
production. Experimental model development belongs on a clearly named branch
and must not silently alter the production launcher.

## Code changes

Run the relevant Python, R, model-contract, and orchestration tests. Add or
update tests for new behavior, preserve fail-safe gates, and keep generated
outputs outside Git. Production and prospective-evaluation pathways must
remain separate; prospective scoring must not refit automatically.
