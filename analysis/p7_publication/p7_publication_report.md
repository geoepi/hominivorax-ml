# P7 Publication Artifact Generation and Release Candidate Assembly Report

## 1. Objective

P7 assembled a reproducible publication package and non-final release candidate
from canonical P0--P6 artifacts without fitting, tuning, recalibrating, or
changing the frozen STRUCTURED_A3 model or qualification results.

## 2. Qualified specification

The package describes STRUCTURED_A3 with the E0_LAST_AVAILABLE issue-time
environmental proxy, horizons 1--3, unchanged P4 support classes, and the
P6_OUTPUT_1.0 production schema. The frozen model hash is
8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e.

## 3. Controlled claims and limitations

The machine-readable claim registry contains eight bounded claim families. Each
primary value traces to a P1--P6 artifact and records its allowed and prohibited
interpretation. Frontier and regional sparsity, count-process bias, environmental
support/extrapolation, E0 dependence, the spatial-holdout boundary, causal
interpretation limits, and source-vintage limits remain explicit.

## 4. Publication artifacts

The build generates five primary tables, eight vector figures, supplementary
source-derived tables, a controlled results synthesis, Methods/Results/Limitations
drafts, a Discussion outline, software and data availability statements, and a
reviewer checklist. Figure and table source metadata are recorded in the result
manifests.

## 5. Reproducibility and safety

The canonical build verifies immutable source hashes and schemas, fails on missing
or mismatched inputs, never invokes model fitting, writes generated files through
temporary paths followed by rename, and records source/output hashes. Two builds
from one commit matched all output hashes except the explicitly permitted manifest
timestamp field. Protected raw data and secrets are excluded.

## 6. Release candidate

The release-candidate metadata use the non-final identifier v1.0.0-rc1. No final
release tag was created. The package is suitable for review, but the documented
tooling and rendering limitations remain part of the audit record.

## 7. P7 decision

`P7_PUBLICATION_PACKAGE_SUPPORTED_WITH_LIMITATIONS`
