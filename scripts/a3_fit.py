#!/usr/bin/env python3
"""P2: invoke the validated single fixed-theta Structured A3 full fit."""

from __future__ import annotations

import json
import sys

from a3_entrypoint_common import common_parser, load_context, run_checked, write_stage_json


def main() -> int:
    args = common_parser(__doc__).parse_args()
    if args.mode != "production_fullfit":
        raise RuntimeError("P2 fitting is only permitted for production_fullfit")
    ctx = load_context(args.config, args.mode, args.run_id)
    output = ctx.output_root
    script = ctx.repo_root / "analysis" / "structured_a3_fullfit" / "scripts" / "run_fullfit_products.py"
    canonical = ctx.canonical_args(output)
    command = [
        sys.executable,
        str(script),
        "fit",
        "--model-output", str(canonical.model_output),
        "--front-features", str(canonical.front_features),
        "--anthropogenic-features", str(canonical.anthropogenic_features),
        "--soil-features", str(canonical.soil_features),
        "--output-root", str(output),
        "--permutation-replicates", "10",
        "--correlation-sample", str(canonical.correlation_sample),
        "--seed", str(canonical.seed),
    ]
    run_checked(command, cwd=ctx.repo_root)
    model_path = output / "model/fullfit_a3_model.json"
    fit_manifest = output / "manifests/fullfit_fit_manifest.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if not model.get("theta_fixed") or float(model.get("theta")) != ctx.scientific["theta"]:
        raise RuntimeError("STOP: fitted model does not preserve frozen theta")
    if float(model.get("penalty")) != ctx.scientific["penalty"] or model.get("objective") != ctx.scientific["objective"]:
        raise RuntimeError("STOP: fitted model specification differs from frozen Structured A3")
    info = model.get("fit_info", {})
    if not info.get("occurrence_success") or not info.get("count_success"):
        raise RuntimeError("STOP: fixed-theta production fit did not converge")
    payload = {
        "status": "fit_complete",
        "stage": "P2",
        "run_id": args.run_id,
        "output_root": str(output),
        "model_path": str(model_path),
        "fit_manifest": str(fit_manifest),
        "fit_end_week": model.get("fit_end_week"),
        "fit_week_count": model.get("fit_week_count"),
        "fit_info": info,
        "theta": model.get("theta"),
        "penalty": model.get("penalty"),
        "objective": model.get("objective"),
    }
    write_stage_json(ctx, "fit_summary.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
