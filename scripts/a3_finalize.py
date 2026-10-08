#!/usr/bin/env python3
"""P5: finalize the run-specific artifact manifest and summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from a3_entrypoint_common import common_parser, load_context, run_checked, write_json, write_stage_json


def main() -> int:
    args = common_parser(__doc__).parse_args()
    ctx = load_context(args.config, args.mode, args.run_id)
    output = ctx.output_root
    if ctx.mode == "production_fullfit":
        script = ctx.repo_root / "analysis" / "structured_a3_fullfit" / "scripts" / "run_fullfit_products.py"
        run_checked([sys.executable, str(script), "finalize", "--output-root", str(output)], cwd=ctx.repo_root)
        artifact_manifest = output / "structured_a3_fullfit_output_manifest.json"
        if not artifact_manifest.exists():
            raise RuntimeError("STOP: full-fit finalization did not produce the artifact manifest")
        artifact = json.loads(artifact_manifest.read_text(encoding="utf-8"))
        payload = {"status": "finalized", "mode": ctx.mode, "run_id": ctx.run_id, "output_root": str(output), "artifact_manifest": str(artifact_manifest), "artifact_count": artifact.get("artifact_count"), "manifest_sha256": artifact.get("manifest_sha256"), "scientific_model_unchanged": True}
    else:
        status_path = output / "manifests/prospective_status.json"
        if not status_path.exists():
            raise RuntimeError("STOP: prospective status is missing before finalization")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        payload = {"status": "finalized", "mode": ctx.mode, "run_id": ctx.run_id, "evaluation_status": status.get("status"), "eligible_weeks": status.get("eligible_weeks", []), "refit_performed": status.get("refit_performed", False), "scientific_model_unchanged": True}
    payload["chime_execution_id"] = ctx.chime_execution_id
    write_stage_json(ctx, "final_summary.json", payload)
    write_json(ctx.log_root / "output_manifest.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
