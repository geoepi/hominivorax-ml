# Computational feasibility and storage

## Observed Atlas qualification costs

Read-only Slurm accounting was retrieved through the approved WSL/Ubuntu Atlas wrapper. Requested memory and sampled batch MaxRSS are distinct.

| Component / job | Elapsed | Requested resources | Batch MaxRSS |
|---|---:|---|---:|
| P1 validation, 21059059 | 00:06:54 | 64G, 16 CPUs | 731,044 KB |
| P2 prepare, 21059228 | 00:00:13 | 64G, 8 CPUs | 1,019,516 KB |
| P2 origin array, 21059244 | 11–21 sec/task; sampled tasks 0/20: 13/19 sec | 64G, 16 CPUs/task | 642,120 / 758,468 KB |
| P2 aggregate, 21059277 | 00:26:41 | 96G, 16 CPUs | 1,114,592 KB |
| P3 robustness, 21059814 | 00:01:49 | 96G, 16 CPUs | 1,313,904 KB |
| P4 support, 21060079 | 00:04:37 | 96G, 16 CPUs | 4,795,768 KB |
| P4 bootstrap, 21060088 | sampled slots 0/119: 12/13 sec | 64G, 16 CPUs/slot | 1,259,568 / 1,222,640 KB |
| P5 input contract, 21060933 | 00:00:38 | 96G, 16 CPUs | 1,055,800 KB |
| P5A proxy metadata | 410.34 sec | resources not retained | not retained |
| W44 candidate full fit, 21272817 | 00:08:47 | 48G, 8 CPUs | 2,926,936 KB |

W44 retrospective P2 replay has 26 origins rather than 21. Do not linearly extrapolate total wall time; queueing, inputs and aggregation differ. Reuse W44 prepared response/features and existing P2/P3/P4/P5A implementations only after separate execution authorization. P3’s three origins × three starts imply nine initialization comparisons. P4 requests 100 successful whole-training-week bootstrap replicates, up to 120 deterministic slots. These are observations, not runtime promises/ceilings. Do not repeat W44 full fit.

## Minimal work and reuse

- Verify candidate identity once; no fit.
- One W44 historical P2 replay: 26 origins, 78 blocks, 782,886 node-horizon rows. One archive feeds compatible P2/P3/P4/P5A summaries.
- Fixed W44 prospective archive: eight weekly origins × three horizons (24 blocks, 240,888 rows) after issue before outcomes; no refit. Ten distinct target weeks cover overlapping horizons.
- P3 bounded summaries plus nine initialization runs.
- P4 W44 support/intervals and 100 successful bootstrap fits, at most 120 slots if required.
- P5A/P7I proxy/issue-time/frontier metrics from archived predictions; no fit.
- P6 isolated workflow checks later; no production writes.
- Optional W16-cutoff diagnostic fit only if history attribution is required.

Historical replay cannot satisfy fixed-W44 post-freeze evidence. A first qualification pass should prioritize identity, the 26-origin replay, prospective issue-time recording, and W44 support/uncertainty; no production decision before P1/operational gates.

## Storage and location

Atlas /project showed 8.1 TB total, 3.6 TB used, 4.5 TB available (44% used). quota -s returned “Operation not permitted”; user/project quota was unavailable. Existing P2 prediction Parquet is 23,770,151 bytes for 632,331 rows; P4 bootstrap target manifest is 2,118,021 bytes. These are measured references, not W44 size estimates. Check quota/destination before execution.

Keep row-level predictions, coordinates, residuals and detailed maps on Atlas. Commit only aggregates, metadata, configuration, code and documentation. No Atlas output was written in this audit.
