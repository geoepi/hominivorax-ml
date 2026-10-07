# STGNN-Hurdle-V1 data provenance

## Frozen source and domain

V1 used the processed observation source:

`/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv`

Its authoritative SHA-256 is
`a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e` and it
contains 136,714 source rows. The retained prediction domain is the revised
Mexico plus U.S.-to-40N footprint: 10,037 nodes, 77,614 directed queen edges,
4 connected components, and 3 isolates.

V1 development responses span 2025-W01 through 2026-W16. The former terminal
period spans 2026-W17 through 2026-W29 and is now historical evaluated data.
No records through 2026-W30 were included in the V1 terminal evaluation.

## V1 provenance records

The model freeze record is
`/project/disease_ecology/STGNN-output/terminal_evaluation/manifests/model_freeze_manifest.json`.
Its SHA-256 is
`d5787cf89e593dc1f70aa9cb60f6ca7f34160f63dac8dd12df491f7157a0895f`.
The graph checksum is
`539876a1528c84f2bf7ab97f5b8f20b3da480cb1c705ac47611542e4a00ad9a7` and the
dataset manifest checksum is
`ce60e713ccaf1651f0a9724bd7209c52ee83ee6efa4613a9ffc3b2882b8c74b7`.

The immutable artifact checksum manifest is stored under
`/project/disease_ecology/STGNN-output/v2_audit/v1_archive/`. It covers the
freeze manifest, frozen model/preprocessing files, terminal predictions, full
metrics, regional metrics, weekly metrics, U.S. ranks, latitude metrics, and
calibration table. The original V1 output directory is not overwritten.

## Response semantics

Counts are the number of recorded detections assigned to a revised-domain
node-week. Presence is one when the count is greater than zero. The data do not
contain an observation-effort denominator, repeated negative surveys, or a
known-at-risk population. These limitations are part of the V1 benchmark
contract and are not repaired retrospectively.
