#!/usr/bin/env python3
"""Persist the exact reference profile used by the frozen effect-response tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPT_ROOT / "analysis" / "predictor_augmentation" / "scripts"))
from run_predictor_augmentation import ADDED_FEATURES, BASE_FEATURES, CALENDAR_FEATURES  # noqa: E402

NODE_COUNT = 10_037
HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p", "any_prior_positive_available",
    "prev4_positive_available", "detection_within_50km_ever_available",
]
FEATURE_ORDER = list(BASE_FEATURES) + list(ADDED_FEATURES)
TRANSFORMATIONS = {
    **{name: "identity" for name in BASE_FEATURES[:12]},
    **{name: "log1p" for name in BASE_FEATURES[12:17]},
    **{name: "identity" for name in BASE_FEATURES[17:22]},
    "week_sin": "identity", "week_cos": "identity",
    "distance_to_any_prior_positive_log1p": "log1p",
    "distance_to_prev4_positive_log1p": "log1p",
    "weeks_since_detection_within_50km_log1p": "log1p",
    "any_prior_positive_available": "identity", "prev4_positive_available": "identity",
    "detection_within_50km_ever_available": "identity",
    "road_density": "log1p", "night_illumination": "log1p",
    "clay_0_15": "identity", "water_difference_wv0033_minus_wv0010_0_15": "identity",
}
UNSCALED = {name for name in FEATURE_ORDER if name.endswith("_imputed") or name.endswith("_available")} | set(CALENDAR_FEATURES)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_nodes(nodes: pd.DataFrame, label: str) -> pd.DataFrame:
    nodes = nodes.sort_values("model_node_id").reset_index(drop=True)
    ids = nodes["model_node_id"].to_numpy(np.int64)
    if len(nodes) != NODE_COUNT or not np.array_equal(ids, np.arange(NODE_COUNT)):
        raise RuntimeError(f"{label} does not cover canonical model_node_id 0..10036")
    return nodes


def build_features(args: argparse.Namespace) -> tuple[np.ndarray, int]:
    raw = args.model_output / "raw"
    horizon = json.loads((args.output_root / "manifests" / "fullfit_data_horizon.json").read_text())
    end = int(horizon["full_fit_week_count"])
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=np.float64)
    weeks = pd.read_parquet(raw / "weeks.parquet").reset_index(drop=True)
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[list(CALENDAR_FEATURES)].to_numpy(np.float64)
    front = pd.read_parquet(args.front_features, columns=["week_index", "model_node_id", *HISTORY_FEATURES, "history_cutoff_week"])
    front = front.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    nodes = validate_nodes(pd.read_parquet(raw / "nodes.parquet"), "canonical node table")
    anthro = validate_nodes(pd.read_parquet(args.anthropogenic_features), "anthropogenic feature table")
    soil = validate_nodes(pd.read_parquet(args.soil_features), "soil feature table")
    soil_map = {name: (name if name in soil.columns else f"{name}__mean") for name in ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"]}
    static_a3 = anthro[["model_node_id", "road_density", "night_illumination"]].merge(soil[["model_node_id", *soil_map.values()]], on="model_node_id", validate="one_to_one").rename(columns={value: key for key, value in soil_map.items()}).sort_values("model_node_id")
    transformed_static = static.copy()
    transformed_static[:, :5] = np.log1p(transformed_static[:, :5])
    added = static_a3[list(ADDED_FEATURES)].to_numpy(np.float64)
    added[:, :2] = np.log1p(added[:, :2])
    history = front[HISTORY_FEATURES].to_numpy(np.float64).reshape(len(weeks), NODE_COUNT, len(HISTORY_FEATURES))
    base = np.concatenate([
        dynamic,
        np.broadcast_to(transformed_static[:, :5][None, :, :], (len(weeks), NODE_COUNT, 5)),
        np.broadcast_to(transformed_static[:, 5:][None, :, :], (len(weeks), NODE_COUNT, 5)),
        np.broadcast_to(calendar[:, None, :], (len(weeks), NODE_COUNT, 2)), history,
    ], axis=2)
    features = np.concatenate([base, np.broadcast_to(added[None, :, :], (len(weeks), NODE_COUNT, len(ADDED_FEATURES)))], axis=2)
    if features.shape != (len(weeks), NODE_COUNT, len(FEATURE_ORDER)):
        raise RuntimeError(f"unexpected reference-profile feature shape: {features.shape}")
    return features, end


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--output-root", type=Path, default=Path("/project/disease_ecology/STGNN-output/structured_a3_fullfit"))
    parser.add_argument("--front-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet"))
    parser.add_argument("--anthropogenic-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet"))
    parser.add_argument("--soil-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet"))
    parser.add_argument("--selected", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selected_path = args.selected or args.output_root / "interpretation" / "effects" / "selected_effect_predictors.csv"
    selected = pd.read_csv(selected_path)["predictor"].astype(str).tolist()
    if len(selected) != 8:
        raise RuntimeError(f"persisted effect selection contains {len(selected)} predictors, expected 8")
    features, end = build_features(args)
    raw = features[:end].reshape(-1, len(FEATURE_ORDER))
    mean = raw.mean(axis=0)
    sd = raw.std(axis=0)
    scaled = (raw - mean) / np.where(sd > 0, sd, 1.0)
    rows = []
    for index, name in enumerate(FEATURE_ORDER):
        if name in UNSCALED:
            model_value = 0.0
            rule = "reference 0 for availability/missingness indicator"
        elif name == "week_sin":
            model_value = 0.0
            rule = "neutral seasonal contribution: week_sin = 0"
        elif name == "week_cos":
            model_value = 1.0
            rule = "representative seasonal contribution: week_cos = 1"
        else:
            model_value = float(np.median(scaled[:, index]))
            rule = "median of full-fit transformed predictor values"
        transformed_value = model_value if name in UNSCALED or name in {"week_sin", "week_cos"} else float(np.median(raw[:, index]))
        natural_value = float(np.expm1(transformed_value)) if TRANSFORMATIONS[name] == "log1p" else transformed_value
        role = "focal_varies" if name in selected else "held_fixed"
        rows.append({
            "predictor": name, "role": role, "transformation": TRANSFORMATIONS[name],
            "reference_rule": rule, "reference_value_model_scale": model_value,
            "reference_value_transformed_scale": transformed_value, "reference_value_natural_scale": natural_value,
            "history_state_note": "availability indicators fixed at 0; history distances otherwise at transformed median" if name in HISTORY_FEATURES else "",
            "source_data": str(args.model_output), "full_fit_week_count": end,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output, index=False)
    print(f"REFERENCE_PROFILE_COMPLETE rows={len(rows)} output={args.output}")


if __name__ == "__main__":
    main()
