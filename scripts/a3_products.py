#!/usr/bin/env python3
"""P4: render validated spatial products and product QA."""

from __future__ import annotations

import json
import subprocess
import sys

from a3_entrypoint_common import common_parser, load_context, read_json_or_yaml, write_stage_json


def main() -> int:
    parser = common_parser(__doc__)
    args = parser.parse_args()
    ctx = load_context(args.config, args.mode, args.run_id)
    output = ctx.output_root
    score = json.loads((ctx.log_root / "score_summary.json").read_text(encoding="utf-8"))
    if ctx.mode == "prospective_evaluation":
        payload = {"status": "products_skipped", "mode": ctx.mode, "run_id": ctx.run_id, "score_status": score.get("status"), "reason": "prospective run has no spatial product contract when no eligible weeks are available"}
        if score.get("status") == "scored":
            payload["status"] = "products_complete"
        write_stage_json(ctx, "products_summary.json", payload)
        print(json.dumps(payload, indent=2))
        return 0
    inputs = ctx.inputs
    mask = ctx.input_path("mask_path")
    if mask is None or not mask.exists():
        raise RuntimeError(f"canonical environment mask is missing: {mask}")
    renderer = ctx.repo_root / "analysis" / "structured_a3_fullfit" / "scripts" / "render_fullfit_spatial.R"
    boundary_root = ctx.input_path("boundary_root", required=False)
    command = ["Rscript", "--vanilla", str(renderer), "--output-root", str(output), "--mask", str(mask)]
    if boundary_root is not None:
        command.extend(["--boundary-root", str(boundary_root)])
    completed = subprocess.run(command, cwd=ctx.repo_root, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"spatial product renderer exited with status {completed.returncode}")
    qa_path = output / "manifests/geotiff_qa.csv"
    if not qa_path.exists():
        raise RuntimeError("STOP: spatial renderer did not produce GeoTIFF QA")
    payload = {"status": "products_complete", "mode": ctx.mode, "run_id": ctx.run_id, "output_root": str(output), "geotiff_qa": str(qa_path)}
    write_stage_json(ctx, "products_summary.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
