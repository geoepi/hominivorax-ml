# Validation status

Development of Structured A3 is complete and the scientific specification is
frozen. The historical exposed holdout is supported under the project’s
documented rubric, but it is not an independent prospective validation.

Current status is intentionally explicit:

- observations currently extend through **2026-W31**;
- complete A3 predictor support currently extends through **2026-W29**;
- the current descriptive full fit covers **2025-W01 through 2026-W29**;
- independent prospective validation is **not yet tested**.

`production_fullfit` is an operational update that refits the frozen model on
the latest authorized complete data. It must not be described as prospective
validation. `prospective_evaluation` scores complete weeks strictly after a
deployed model’s frozen evaluation horizon without refitting.
