#!/usr/bin/env python3
"""P0: validate the frozen Structured A3 production data horizon."""

from __future__ import annotations

import json
import sys

from a3_entrypoint_common import common_parser, ensure_input_paths, leakage_payload, load_context, load_fullfit_module, write_stage_json


def main() -> int:
    args = common_parser(__doc__).parse_args()
    ctx = load_context(args.config, args.mode, args.run_id)
    paths = ensure_input_paths(ctx)
    if args.mode == "prospective_evaluation":
        from a3_pipeline import validate_deployed_manifest

        validate_deployed_manifest(ctx.config, ctx.scientific)
    module = load_fullfit_module(ctx.repo_root)
    bundle = module.load_bundle(ctx.canonical_args())
    horizon, support = module.completeness(bundle)
    leakage = leakage_payload(support)
    if leakage["status"] != "PASS":
        raise RuntimeError("STOP: Structured A3 history leakage preflight failed")
    payload = {
        "status": "PASS",
        "stage": "P0",
        "mode": args.mode,
        "run_id": args.run_id,
        "repository_sha": __import__("a3_pipeline").git_sha(ctx.repo_root),
        "input_paths": paths,
        "horizon": horizon,
        "leakage_audit": leakage,
        "complete_support_weeks": support.loc[support["complete_fit_support"], "week"].astype(str).tolist(),
    }
    write_stage_json(ctx, "preflight_summary.json", payload)
    write_stage_json(ctx, "leakage_audit.json", leakage, output_copy=False)
    module.write_csv(ctx.output_root / "manifests/preflight_support_audit.csv", support)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
