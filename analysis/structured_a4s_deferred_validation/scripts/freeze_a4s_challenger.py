#!/usr/bin/env python3
"""Fit the selected A4-S challenger once and freeze its evaluation contract.

This entrypoint is intentionally narrower than the architecture comparison.
It imports the already-reviewed A4-S implementation, uses the same 68-week
development endpoint, performs exactly one fixed fit, and writes the model
artifact outside Git. It never reads prospective outcomes for selection and it
never modifies the production A3 assets.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPOSITORY_ROOT = Path(os.environ.get("A4_REPOSITORY_ROOT", Path(__file__).resolve().parents[3])).resolve()
BASELINE_SHA = "93f7ce1aef603f63eab5aecc5bbaaa6ce6bba1fc"
ARCHITECTURE_COMPARISON_SHA = "93f7ce1aef603f63eab5aecc5bbaaa6ce6bba1fc"
NODE_COUNT = 10_037
FIT_START = "2025-W01"
FIT_END = "2026-W16"
FIT_WEEK_COUNT = 68
PROSPECTIVE_WEEKS = tuple(f"2026-W{week:02d}" for week in range(30, 40))
FREEZE_WEEK = "2026-W42"
ELIGIBLE_WEEK = "2026-W43"
MODEL_ID = "STRUCTURED_A4S_CHALLENGER"
FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean",
    "era5land_lai_low_mean", "cattle_density", "goat_density", "sheep_density",
    "horse_density", "pig_density", "cattle_density_imputed",
    "goat_density_imputed", "sheep_density_imputed", "horse_density_imputed",
    "pig_density_imputed", "week_sin", "week_cos",
    "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p", "any_prior_positive_available",
    "prev4_positive_available", "detection_within_50km_ever_available",
    "road_density", "night_illumination", "clay_0_15",
    "water_difference_wv0033_minus_wv0010_0_15",
]
TRANSFORMATIONS = {
    "environmental_predictors": "identity_then_development_only_standardization",
    "livestock_density_predictors": "log1p_then_development_only_standardization",
    "livestock_imputation_indicators": "identity_unscaled",
    "calendar_predictors": "identity_unscaled",
    "distance_to_any_prior_positive_log1p": "causal_log1p_projected_km_then_development_only_standardization",
    "distance_to_prev4_positive_log1p": "causal_log1p_projected_km_then_development_only_standardization",
    "weeks_since_detection_within_50km_log1p": "causal_log1p_weeks_then_development_only_standardization",
    "history_availability_indicators": "identity_unscaled",
    "road_density": "log1p_then_development_only_standardization",
    "night_illumination": "log1p_then_development_only_standardization",
    "clay_0_15": "identity_then_development_only_standardization",
    "water_difference_wv0033_minus_wv0010_0_15": "identity_then_development_only_standardization",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_a4_module() -> Any:
    path = REPOSITORY_ROOT / "analysis" / "structured_a4_comparison" / "scripts" / "run_a4_comparison.py"
    spec = importlib.util.spec_from_file_location("frozen_a4_comparison_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import reviewed A4 comparison source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPOSITORY_ROOT.as_posix()}", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT, text=True,
        ).strip()
    except Exception:
        return "unknown"


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    if args.freeze_week != FREEZE_WEEK or args.eligible_week != ELIGIBLE_WEEK:
        raise RuntimeError("Freeze boundary must remain 2026-W42 with first eligible week 2026-W43")
    config_path = REPOSITORY_ROOT / "analysis" / "structured_a4_comparison" / "config" / "a4_comparison_config.json"
    config = read_json(config_path)
    if config["baseline_repository_sha"] != "fae2d0f08c72a018338b9359543cfd2b88d7d8e2":
        raise RuntimeError("A4 comparison configuration provenance changed")
    if tuple(config["development_period"]["excluded_prospective_weeks"]) != PROSPECTIVE_WEEKS:
        raise RuntimeError("A4 comparison did not exclude exactly W30-W39")
    if config["sit"]["included"]:
        raise RuntimeError("SIT covariates are forbidden")

    a4 = load_a4_module()
    args_for_loader = argparse.Namespace(
        model_output=args.model_output,
        front_features=args.front_features,
        soil_features=args.soil_features,
        anthropogenic_features=args.anthropogenic_features,
        edges=args.edges,
        observation_source=args.observation_source,
        a3_fold_reference=args.a3_fold_reference,
        config=config_path,
    )
    data = a4.load_data(args_for_loader, config)
    labels = data.weeks["iso_week"].astype(str).tolist()
    expected = [f"2025-W{week:02d}" for week in range(1, 53)] + [f"2026-W{week:02d}" for week in range(1, 17)]
    if labels[:FIT_WEEK_COUNT] != expected or len(data.a3) != FIT_WEEK_COUNT:
        raise RuntimeError("A4-S fit horizon is not exactly 2025-W01 through 2026-W16")
    if set(labels[:FIT_WEEK_COUNT]).intersection(PROSPECTIVE_WEEKS):
        raise RuntimeError("W30-W39 entered the challenger fit")
    if len(data.counts) < FIT_WEEK_COUNT * NODE_COUNT:
        raise RuntimeError("The authorized development response array is incomplete")

    raw_train = data.a3.reshape(-1, data.a3.shape[2]).astype(np.float64, copy=False)
    y_train = data.counts[:FIT_WEEK_COUNT].reshape(-1)
    if len(y_train) != FIT_WEEK_COUNT * NODE_COUNT:
        raise RuntimeError("Unexpected training response size")

    # This is the selected A4-S call from the merged comparison source. The
    # eval array is deliberately the same frozen development array solely so
    # that the selected residual effects can be materialized once.
    solver = a4.make_graph_solver(data.laplacian, float(config["a4_s"]["graph_lambda"]))
    state, _, _, _, fit_info = a4.fit_candidate("A4-S", raw_train, y_train, raw_train, solver, config)
    x_train, _, scaling = a4.standardize(raw_train, raw_train, FEATURES)
    p_train, cond_train, _ = a4.predict_state(state, x_train)
    train_weeks = np.asarray(y_train, dtype=np.float64).reshape(FIT_WEEK_COUNT, NODE_COUNT)
    p_train_weeks = p_train.reshape(FIT_WEEK_COUNT, NODE_COUNT)
    cond_train_weeks = cond_train.reshape(FIT_WEEK_COUNT, NODE_COUNT)
    residual_scale = float(config["a4_s"]["residual_scale"])
    occurrence_effect = a4.smooth_graph_effect(
        (train_weeks > 0).mean(axis=0) - p_train_weeks.mean(axis=0), solver, residual_scale,
    )
    positive_mask = train_weeks > 0
    log_residual = np.zeros_like(train_weeks, dtype=np.float64)
    log_residual[positive_mask] = np.log1p(train_weeks[positive_mask]) - np.log1p(cond_train_weeks[positive_mask])
    positive_counts = positive_mask.sum(axis=0)
    count_residual = np.divide(
        log_residual.sum(axis=0), positive_counts, out=np.zeros(NODE_COUNT, dtype=np.float64), where=positive_counts > 0,
    )
    count_effect = a4.smooth_graph_effect(count_residual, solver, residual_scale)
    if not np.isfinite(occurrence_effect).all() or not np.isfinite(count_effect).all():
        raise RuntimeError("A4-S spatial effects are non-finite")

    args.output_root.mkdir(parents=True, exist_ok=True)
    artifact_npz = args.output_root / "frozen_a4s_model.npz"
    artifact_json = args.output_root / "frozen_a4s_model.json"
    if artifact_npz.exists() or artifact_json.exists() or args.manifest_output.exists():
        raise RuntimeError("refusing to overwrite an existing A4-S freeze artifact or manifest")
    np.savez_compressed(
        artifact_npz,
        occurrence_beta=np.asarray(state["occurrence_beta"], dtype=np.float64),
        count_beta=np.asarray(state["count_beta"], dtype=np.float64),
        training_mean=np.asarray(scaling["training_mean"], dtype=np.float64),
        training_sd=np.asarray(scaling["training_sd"], dtype=np.float64),
        occurrence_spatial_effect=np.asarray(occurrence_effect, dtype=np.float64),
        count_spatial_effect=np.asarray(count_effect, dtype=np.float64),
    )
    artifact_payload = {
        "model_id": MODEL_ID,
        "status": "FROZEN_FOR_DEFERRED_INDEPENDENT_EVALUATION",
        "arrays_file": artifact_npz.name,
        "feature_count": len(FEATURES),
        "feature_order": FEATURES,
        "transformations": TRANSFORMATIONS,
        "objective": "exact_joint_hurdle_nll",
        "theta": float(state["theta"]),
        "theta_fixed": True,
        "penalty": float(config["model"]["penalty_a3"]),
        "spatial_formulation": "graph-Laplacian residual effect; (I + lambda L)^-1 centered node residual",
        "graph_lambda": float(config["a4_s"]["graph_lambda"]),
        "residual_scale": residual_scale,
        "graph_solver": {"method": "conjugate_gradient", "rtol": 1e-8, "atol": 1e-10, "maxiter": 500},
        "domain": {"node_count": NODE_COUNT, "node_id_rule": "0 through 10036 canonical revised-domain order"},
        "training_period": {"start": FIT_START, "end": FIT_END, "week_count": FIT_WEEK_COUNT},
        "training_prevalence": float(np.mean(y_train > 0)),
        "fit_info": fit_info,
        "spatial_effect_summary": {
            "occurrence_effect_sd": float(np.std(occurrence_effect)),
            "count_effect_sd": float(np.std(count_effect)),
            "occurrence_effect_max_abs": float(np.max(np.abs(occurrence_effect))),
            "count_effect_max_abs": float(np.max(np.abs(count_effect))),
        },
        "software": {"python": platform.python_version(), "numpy": np.__version__, "repository_sha_at_fit": git_head()},
    }
    write_json(artifact_json, artifact_payload)

    input_hashes = {key: {"path": str(path), "sha256": sha256_file(path)} for key, path in data.paths.items() if path.exists()}
    input_hashes["a4_comparison_config"] = {"path": str(config_path), "sha256": sha256_file(config_path)}
    artifact_hashes = {"model_npz": sha256_file(artifact_npz), "model_json": sha256_file(artifact_json)}
    manifest = {
        "manifest_version": "1.0.0",
        "model": {
            "id": MODEL_ID, "status": "FROZEN_FOR_DEFERRED_INDEPENDENT_EVALUATION",
            "predictor_count": len(FEATURES), "predictor_order": FEATURES,
            "transformations": TRANSFORMATIONS, "objective": "exact_joint_hurdle_nll",
            "theta": float(state["theta"]), "penalty": float(config["model"]["penalty_a3"]),
            "spatial_formulation": artifact_payload["spatial_formulation"],
            "graph_lambda": float(config["a4_s"]["graph_lambda"]),
            "residual_scale": residual_scale,
        },
        "development_provenance": {
            "architecture_comparison_merge_sha": ARCHITECTURE_COMPARISON_SHA,
            "baseline_repository_sha": BASELINE_SHA,
            "development_folds": config["folds"],
            "development_endpoint": {"start": FIT_START, "end": FIT_END, "week_count": FIT_WEEK_COUNT},
            "selection_data_endpoint": "A4 F1-F4 pre-W30 development folds",
            "w30_w39_excluded": True,
            "a4_comparison_decision": "HOLD — NO A4 CANDIDATE JUSTIFIED",
            "challenger_context": "A4-S was the strongest provisional challenger and was not advanced",
        },
        "evaluation_boundary": {
            "challenger_freeze_week": FREEZE_WEEK,
            "evaluation_eligible_week": ELIGIBLE_WEEK,
            "fit_horizon_end": FIT_END,
            "post_freeze_outcomes_required": True,
            "w30_w39_independent_evaluation_forbidden": True,
        },
        "scientific_caveats": {
            "observation_reporting_bias": "unresolved",
            "reporting_effort_covariates_available": False,
            "latent_incidence_claim": False,
            "sit_status": "RESERVED_FUTURE_INTERVENTION_LAYER",
            "sit_covariates_included": False,
            "us_counts_and_progression": "INTERVENTION_CONFOUNDED",
            "us_transfer_ranking_pre_w30": "not assessable",
        },
        "evaluation_restrictions": {
            "no_refit_after_freeze": True, "no_recalibration": True, "no_threshold_tuning": True,
            "no_feature_selection": True, "no_spatial_parameter_retuning": True,
            "no_post_freeze_outcomes_for_model_changes": True,
        },
        "artifact": {"root": str(args.output_root), "json": str(artifact_json), "npz": str(artifact_npz), "sha256": artifact_hashes},
        "inputs": input_hashes,
        "generated_utc": utc_now(),
        "freeze_script_sha256": sha256_file(Path(__file__)),
    }
    manifest_path = args.manifest_output
    write_json(manifest_path, manifest)
    manifest_sha = sha256_file(manifest_path)
    sidecar = manifest_path.with_name(manifest_path.name + ".sha256")
    sidecar.write_text(f"{manifest_sha}  {manifest_path.name}\n", encoding="utf-8")
    return {"status": "completed", "model_id": MODEL_ID, "manifest": str(manifest_path), "manifest_sha256": manifest_sha, "artifact": str(args.output_root)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--observation-source", type=Path, required=True)
    parser.add_argument("--a3-fold-reference", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--freeze-week", default=FREEZE_WEEK)
    parser.add_argument("--eligible-week", default=ELIGIBLE_WEEK)
    args = parser.parse_args()
    print(json.dumps(freeze(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
