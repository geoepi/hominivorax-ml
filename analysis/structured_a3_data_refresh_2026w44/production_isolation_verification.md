# Production isolation verification

- Atlas production code checkout: /project/disease_ecology/STGNN-production at b1095e7fc8ef94ce4613aa7adcdc643e76a2e927.
- Atlas production configuration: /project/disease_ecology/STGNN-production-config/atlas-production.yaml, SHA-256 f51038b5fe553f1281418d7ed2c9f1060ca8fe32957708c80bbc7332b89b1e3d.
- Current configured observation source remains combined_clean_obs_2027-07-31.csv.
- Existing production output root remains /project/disease_ecology/STGNN-output/a3_production.
- Existing fullfit output remains /project/disease_ecology/STGNN-output/structured_a3_fullfit.
- Existing current fullfit model SHA-256 is recorded as 1cb694f4323ac2d05d973b5631539bd4e3a95ed3ffe3a7405a9e35c6b377092e in its manifest.
- The separate proposed path /project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44 did not exist at audit time.
- No Atlas file was written, no production pointer or configuration was changed, and no Slurm job was submitted.

This is a read-only isolation check. The candidate was not built, and the current fullfit remains the pre-existing 2025-W01 through 2026-W29 artifact.
