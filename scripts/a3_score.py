#!/usr/bin/env python3
"""P3: validate fit predictions or score eligible weeks with a frozen model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from a3_entrypoint_common import (
    common_parser,
    deployed_model_path,
    load_context,
    load_fullfit_module,
    read_json_or_yaml,
    week_tuple,
    write_stage_json,
)


def production_score(ctx) -> dict:
    output = ctx.output_root
    model_path = output / "model/fullfit_a3_model.json"
    prediction_path = output / "predictions/weekly_predictions.parquet"
    if not model_path.exists() or not prediction_path.exists():
        raise RuntimeError("STOP: production fit artifacts are missing before score stage")
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if not model.get("theta_fixed") or float(model.get("theta")) != ctx.scientific["theta"] or float(model.get("penalty")) != ctx.scientific["penalty"] or model.get("objective") != ctx.scientific["objective"]:
        raise RuntimeError("STOP: production score model specification mismatch")
    info = model.get("fit_info", {})
    if not info.get("occurrence_success") or not info.get("count_success"):
        raise RuntimeError("STOP: production score model is not converged")
    predictions = pd.read_parquet(prediction_path, columns=["week", "model_node_id", "p_occurrence", "conditional_count_mean", "expected_count"])
    if len(predictions) != int(model["fit_week_count"]) * int(ctx.scientific["node_count"]):
        raise RuntimeError("STOP: production prediction archive has an unexpected row count")
    if predictions[["p_occurrence", "conditional_count_mean", "expected_count"]].isna().any().any():
        raise RuntimeError("STOP: production prediction archive contains missing scores")
    return {
        "status": "score_complete",
        "mode": "production_fullfit",
        "run_id": ctx.run_id,
        "fit_end_week": model.get("fit_end_week"),
        "scored_week_count": int(model["fit_week_count"]),
        "scored_node_count": int(ctx.scientific["node_count"]),
        "refit_performed_in_stage": False,
        "model_sha256": __import__("a3_pipeline").sha256_file(model_path),
    }


def prospective_score(ctx, no_refit: bool) -> dict:
    if not no_refit:
        raise RuntimeError("STOP: prospective score entrypoint requires --no-refit")
    from a3_pipeline import validate_deployed_manifest

    validate_deployed_manifest(ctx.config, ctx.scientific)
    deployment_path = ctx.input_path("deployed_model_manifest")
    assert deployment_path is not None
    deployment = read_json_or_yaml(deployment_path)
    model_path = deployed_model_path(ctx, deployment)
    if not model_path.exists():
        raise RuntimeError(f"STOP: frozen deployed model artifact is missing: {model_path}")
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if not model.get("theta_fixed") or float(model.get("theta")) != ctx.scientific["theta"] or float(model.get("penalty")) != ctx.scientific["penalty"] or model.get("objective") != ctx.scientific["objective"]:
        raise RuntimeError("STOP: deployed model specification mismatch")
    module = load_fullfit_module(ctx.repo_root)
    bundle = module.load_bundle(ctx.canonical_args())
    horizon, support = module.completeness(bundle)
    evaluation_end = str(__import__("a3_pipeline").lookup(deployment, ("evaluation_end_week", "evaluation_horizon", "evaluation_end")))
    eligible = [index for index, row in support.iterrows() if bool(row["complete_fit_support"]) and week_tuple(str(row["week"])) > week_tuple(evaluation_end)]
    output = ctx.output_root
    if not eligible:
        payload = {
            "status": "no_eligible_weeks",
            "mode": "prospective_evaluation",
            "run_id": ctx.run_id,
            "evaluation_end_week": evaluation_end,
            "latest_complete_supported_week": horizon["full_fit_end_week"],
            "eligible_weeks": [],
            "refit_performed": False,
            "frozen_model_path": str(model_path),
            "reason": "no complete predictor-supported weeks exist strictly after the deployed evaluation horizon",
        }
        write_stage_json(ctx, "prospective_status.json", payload)
        return payload
    raw = bundle["features"][eligible].reshape(-1, len(module.FEATURE_ORDER)).astype(np.float64, copy=False)
    scaling = model["scaling"]
    mean = np.asarray(scaling["training_mean"], dtype=np.float64)
    sd = np.asarray(scaling["training_sd"], dtype=np.float64)
    x = (raw - mean[None, :]) / sd[None, :]
    state = {"occurrence_beta": np.asarray(model["occurrence_coefficients"], dtype=np.float64), "count_beta": np.asarray(model["count_coefficients"], dtype=np.float64)}
    probability, conditional, _ = module.predict(state, x)
    probability = probability.reshape(len(eligible), module.NODE_COUNT)
    conditional = conditional.reshape(len(eligible), module.NODE_COUNT)
    frames = []
    for local_index, source_index in enumerate(eligible):
        frame = bundle["nodes"][["model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region"]].copy()
        frame.insert(0, "week", bundle["labels"][source_index])
        frame["p_occurrence"] = probability[local_index]
        frame["conditional_count_mean"] = conditional[local_index]
        frame["expected_count"] = probability[local_index] * conditional[local_index]
        frame["observed_count"] = bundle["counts"][source_index]
        frames.append(frame)
    predictions = pd.concat(frames, ignore_index=True)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output / "predictions/prospective_predictions.parquet", index=False)
    payload = {
        "status": "scored",
        "mode": "prospective_evaluation",
        "run_id": ctx.run_id,
        "evaluation_end_week": evaluation_end,
        "eligible_weeks": [bundle["labels"][index] for index in eligible],
        "refit_performed": False,
        "frozen_model_path": str(model_path),
        "prediction_path": str(output / "predictions/prospective_predictions.parquet"),
    }
    write_stage_json(ctx, "prospective_status.json", payload)
    return payload


def main() -> int:
    parser = common_parser(__doc__)
    parser.add_argument("--no-refit", action="store_true")
    args = parser.parse_args()
    ctx = load_context(args.config, args.mode, args.run_id)
    payload = production_score(ctx) if args.mode == "production_fullfit" else prospective_score(ctx, args.no_refit)
    write_stage_json(ctx, "score_summary.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
