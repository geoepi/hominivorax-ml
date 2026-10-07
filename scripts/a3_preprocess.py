#!/usr/bin/env python3
"""P1: assemble and persist the validated Structured A3 input manifest."""

from __future__ import annotations

import json

from a3_entrypoint_common import common_parser, ensure_input_paths, leakage_payload, load_context, load_fullfit_module, write_stage_json


def main() -> int:
    args = common_parser(__doc__).parse_args()
    ctx = load_context(args.config, args.mode, args.run_id)
    paths = ensure_input_paths(ctx)
    module = load_fullfit_module(ctx.repo_root)
    bundle = module.load_bundle(ctx.canonical_args())
    horizon, support = module.completeness(bundle)
    leakage = leakage_payload(support)
    if leakage["status"] != "PASS":
        raise RuntimeError("STOP: preprocessing history leakage audit failed")
    output = ctx.output_root
    output.mkdir(parents=True, exist_ok=True)
    module.write_json(output / "manifests/fullfit_data_horizon.json", horizon)
    module.write_csv(output / "manifests/fullfit_support_audit.csv", support)
    payload = {
        "status": "preprocessed",
        "stage": "P1",
        "mode": args.mode,
        "run_id": args.run_id,
        "input_paths": paths,
        "horizon": horizon,
        "feature_order": module.FEATURE_ORDER,
        "predictor_count": len(module.FEATURE_ORDER),
        "node_count": module.NODE_COUNT,
        "leakage_audit": leakage,
    }
    write_stage_json(ctx, "preprocessing_manifest.json", payload)
    write_stage_json(ctx, "leakage_audit.json", leakage, output_copy=False)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
