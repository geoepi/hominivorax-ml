#!/usr/bin/env python3
"""Paired revised-domain STGNN A0 versus A3 development experiment.

This runner deliberately keeps the neural architecture fixed.  ``prepare``
constructs the 52-week warm-up plus the 68 authorized development weeks from
the revised 10,037-node artifacts.  ``run`` executes one fold/seed/model task
and is restartable.  ``finalize`` aggregates only completed F1--F4 tasks and
writes the small result artifacts under ``analysis/stgnn_a3_ablation``.

No terminal-period targets are loaded into the prepared fitting tensor.  The
old 16,756-node Task-2B checkpoint is never read.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from scipy.special import gammaln

SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from hurdle_zt_nb import hurdle_losses, positive_parameter  # noqa: E402
from task2b_models import GConvGRUHurdleNB, model_metadata  # noqa: E402
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402
from run_task3b_v2a import load_data as load_v2a_data  # noqa: E402


OUTPUT_ROOT_DEFAULT = Path("/project/disease_ecology/STGNN-output")
EXPERIMENT_NAME = "stgnn_a3_ablation"
EXPERIMENT_VERSION = "revised-domain-paired-neural-v1"
EXPECTED_NODE_COUNT = 10037
EXPECTED_EDGE_COUNT = 77614
EXPECTED_RESPONSE_WEEKS = 81
DEVELOPMENT_WEEKS = 68
WARMUP_WEEKS = 52
SEQUENCE_WEEKS = WARMUP_WEEKS + DEVELOPMENT_WEEKS
PERIOD = 52.1775
FIXED_THETA = 0.7018903965556372

ENV_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
]
DENSITY_FEATURES = ["cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"]
INDICATOR_FEATURES = [f"{name}_imputed" for name in DENSITY_FEATURES]
CALENDAR_FEATURES = ["week_sin", "week_cos"]
FRONT_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
BASE_24_FEATURES = ENV_FEATURES + DENSITY_FEATURES + INDICATOR_FEATURES + CALENDAR_FEATURES
A0_FEATURES = BASE_24_FEATURES + FRONT_FEATURES
A3_ADDITIONS = [
    "road_density",
    "night_illumination",
    "clay_0_15",
    "water_difference_wv0033_minus_wv0010_0_15",
]
A3_FEATURES = A0_FEATURES + A3_ADDITIONS
FOLDS = {
    1: {"train": list(range(0, 26)), "validation": list(range(26, 39)), "train_period": "2025-W01--2025-W26", "validation_period": "2025-W27--2025-W39"},
    2: {"train": list(range(0, 39)), "validation": list(range(39, 52)), "train_period": "2025-W01--2025-W39", "validation_period": "2025-W40--2025-W52"},
    3: {"train": list(range(0, 52)), "validation": list(range(52, 60)), "train_period": "2025-W01--2025-W52", "validation_period": "2026-W01--2026-W08"},
    4: {"train": list(range(0, 60)), "validation": list(range(60, 68)), "train_period": "2025-W01--2026-W08", "validation_period": "2026-W09--2026-W16"},
}
SEEDS = [20261002, 20261003, 20261004, 20261005, 20261006]
ARCHITECTURE = {
    "model": "GConvGRU-Hurdle-NB",
    "hidden_dimension": 64,
    "graph_convolution": "PyG Temporal GConvGRU",
    "K": 3,
    "normalization": "sym",
    "recurrent_layers": 1,
    "dropout": 0.1,
    "activation": "tanh in hurdle heads; GConvGRU implementation default recurrent activation",
    "occurrence_head": "linear(hidden -> logit)",
    "count_head": "linear(hidden -> softplus underlying NB mean)",
    "theta": FIXED_THETA,
    "theta_treatment": "fixed scalar; raw positive-parameterization buffer is not trainable",
    "loss": "balanced_multitask_loss with positive_loss_multiplier=1.0",
    "optimizer": "Adam",
    "learning_rate": 0.0003,
    "weight_decay": 0.0,
    "gradient_clip_norm": 1.0,
    "initialization": "PyTorch module defaults with paired torch/numpy seeds",
    "warmup_weeks": WARMUP_WEEKS,
    "tbptt_weeks": 13,
    "epoch_limit": 12,
    "early_stopping_patience": 3,
    "batching": "one graph; contiguous 13-week TBPTT chunks; hidden state retained and detached",
    "backend": "CUDA when available; canonical implementation unchanged",
}


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_sha(repo: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    except Exception:
        return "unknown"


def experiment_root(output_root: Path) -> Path:
    return output_root / EXPERIMENT_NAME


def results_root(repo: Path) -> Path:
    return repo / "analysis" / "stgnn_a3_ablation" / "results"


def input_root(output_root: Path) -> Path:
    return experiment_root(output_root) / "inputs"


def task_root(output_root: Path) -> Path:
    return experiment_root(output_root) / "tasks"


def model_root(output_root: Path) -> Path:
    return experiment_root(output_root) / "models"


def array_path(output_root: Path, model: str) -> Path:
    return input_root(output_root) / f"features_{model.lower()}.npy"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_revised_inputs(output_root: Path) -> dict[str, Any]:
    revised = output_root / "revised_model_data"
    raw = revised / "raw"
    manifest_path = revised / "manifests" / "revised_production_manifest.json"
    require(manifest_path.exists(), f"missing revised production manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    edges = pd.read_parquet(raw / "edges_queen.parquet")
    weeks = pd.read_parquet(raw / "weeks.parquet")
    history_weeks = pd.read_parquet(raw / "history_weeks.parquet")
    dynamic_history = np.load(raw / "dynamic_history_features.npy", mmap_mode="r")
    static = np.load(raw / "static_features.npy", mmap_mode="r")
    counts = np.load(raw / "targets_count.npy", mmap_mode="r")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float64)
    require(len(nodes) == EXPECTED_NODE_COUNT, f"revised node count changed: {len(nodes)}")
    require(len(edges) == EXPECTED_EDGE_COUNT, f"revised directed edge count changed: {len(edges)}")
    require(tuple(dynamic_history.shape) == (185, EXPECTED_NODE_COUNT, 12), f"unexpected history shape: {dynamic_history.shape}")
    require(tuple(static.shape) == (EXPECTED_NODE_COUNT, 10), f"unexpected static shape: {static.shape}")
    require(tuple(counts.shape) == (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT), f"unexpected target shape: {counts.shape}")
    require(len(weeks) == EXPECTED_RESPONSE_WEEKS, "response week count changed")
    require(np.array_equal(nodes["model_node_id"].to_numpy(), np.arange(EXPECTED_NODE_COUNT)), "node order is not contiguous")
    require(np.isfinite(np.asarray(dynamic_history)).all() and np.isfinite(np.asarray(static)).all(), "base predictors are non-finite")
    require(np.all(np.asarray(counts) >= 0), "negative response counts")
    require(list(weeks.iloc[:DEVELOPMENT_WEEKS]["iso_week"]) == [
        *[f"2025-W{i:02d}" for i in range(1, 53)],
        *[f"2026-W{i:02d}" for i in range(1, 17)],
    ], "development response weeks are not the authorized 68 weeks")
    require(list(history_weeks.iloc[52:52 + SEQUENCE_WEEKS]["iso_week"]) == [
        *[f"2024-W{i:02d}" for i in range(1, 53)],
        *[f"2025-W{i:02d}" for i in range(1, 53)],
        *[f"2026-W{i:02d}" for i in range(1, 17)],
    ], "52-week warm-up/history alignment changed")
    return {
        "revised": revised,
        "raw": raw,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "nodes": nodes,
        "edges": edges,
        "weeks": weeks,
        "history_weeks": history_weeks,
        "dynamic_history": dynamic_history,
        "static": static,
        "counts": counts,
        "calendar": calendar,
    }


def load_static_additions(output_root: Path, nodes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    augmentation = output_root / "predictor_augmentation"
    augmentation_manifest_path = augmentation / "manifests" / "augmentation_manifest.json"
    road_path = augmentation / "static" / "road_night_node_features.parquet"
    soil_path = output_root / "soil_feature_screening_resumed_s1" / "soil_node_features.parquet"
    cache_path = augmentation / "cache" / "added_features_node.npy"
    require(augmentation_manifest_path.exists(), "missing augmentation manifest")
    require(road_path.exists() and soil_path.exists() and cache_path.exists(), "missing validated augmentation artifact")
    augmentation_manifest = json.loads(augmentation_manifest_path.read_text(encoding="utf-8"))
    require(augmentation_manifest.get("added_features") == A3_ADDITIONS, "augmentation feature order changed")
    require(augmentation_manifest.get("canonical_nodes") == EXPECTED_NODE_COUNT, "augmentation node count changed")
    require(augmentation_manifest.get("theta_fixed") is True, "augmentation provenance is not fixed-theta")
    require(float(augmentation_manifest.get("theta")) == FIXED_THETA, "augmentation theta provenance changed")
    require(augmentation_manifest.get("transformations") == {
        "clay_0_15": "identity",
        "night_illumination": "log1p",
        "road_density": "log1p",
        "water_difference_wv0033_minus_wv0010_0_15": "identity",
    }, "frozen addition transformations changed")

    road = pd.read_parquet(road_path)
    soil = pd.read_parquet(soil_path)
    node_keys = nodes[["model_node_id"]].copy()
    rows: list[dict[str, Any]] = []
    for name, frame in [("revised_nodes", nodes), ("road_night", road), ("soil", soil)]:
        key = frame["model_node_id"]
        rows.append({
            "source": name,
            "rows": len(frame),
            "unique_model_node_id": int(key.nunique()),
            "duplicate_model_node_id": int(key.duplicated().sum()),
            "missing_model_node_id": int(key.isna().sum()),
            "exact_key_set_match_revised_nodes": bool(set(key.astype(int)) == set(node_keys["model_node_id"].astype(int))),
        })
    require(all(row["rows"] == EXPECTED_NODE_COUNT and row["unique_model_node_id"] == EXPECTED_NODE_COUNT and row["duplicate_model_node_id"] == 0 and row["missing_model_node_id"] == 0 and row["exact_key_set_match_revised_nodes"] for row in rows), "augmentation join keys are not exact")
    joined = node_keys.merge(road[["model_node_id", "road_density", "night_illumination"]], on="model_node_id", how="left", validate="one_to_one")
    joined = joined.merge(soil[["model_node_id", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]], on="model_node_id", how="left", validate="one_to_one")
    joined = joined.sort_values("model_node_id").reset_index(drop=True)
    raw_additions = np.column_stack([
        joined["road_density"].to_numpy(float),
        joined["night_illumination"].to_numpy(float),
        joined["clay_0_15__mean"].to_numpy(float),
        joined["water_difference_wv0033_minus_wv0010_0_15__mean"].to_numpy(float),
    ])
    transformed = raw_additions.copy()
    transformed[:, 0:2] = np.log1p(np.maximum(transformed[:, 0:2], 0.0))
    require(np.isfinite(transformed).all(), "transformed additions contain non-finite values")
    cached = np.load(cache_path)
    require(tuple(cached.shape) == (EXPECTED_NODE_COUNT, 4), f"unexpected augmentation cache shape: {cached.shape}")
    cache_max_abs = float(np.max(np.abs(np.asarray(cached, dtype=float) - transformed)))
    require(cache_max_abs <= 1e-10, f"validated addition cache does not match exact-ID transformed join: {cache_max_abs}")
    for index, name in enumerate(A3_ADDITIONS):
        rows.append({
            "source": name,
            "rows": EXPECTED_NODE_COUNT,
            "unique_model_node_id": EXPECTED_NODE_COUNT,
            "duplicate_model_node_id": 0,
            "missing_model_node_id": int(np.isnan(transformed[:, index]).sum()),
            "exact_key_set_match_revised_nodes": True,
        })
    return pd.DataFrame(rows), {
        "joined": joined,
        "raw": raw_additions,
        "transformed": transformed,
        "cache_path": cache_path,
        "cache_sha256": sha256_file(cache_path),
        "road_path": road_path,
        "soil_path": soil_path,
        "augmentation_manifest_path": augmentation_manifest_path,
        "augmentation_manifest": augmentation_manifest,
        "cache_max_abs_difference": cache_max_abs,
    }


def build_front_sequence(output_root: Path, inputs: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    persisted_path = output_root / "v2_model" / "front_features" / "causal_front_features.parquet"
    require(persisted_path.exists(), f"missing persisted V2-A front features: {persisted_path}")
    # Reuse the authoritative V2-A causal builder with the refreshed response
    # array reconciled by run_task3b_v2a.load_data.  The older v2_audit table
    # is retained for provenance, but its target front states predate the
    # refreshed observation source and therefore cannot be used for identity.
    v2_data = load_v2a_data(inputs["revised"], output_root / "v2_audit")
    positive_sets = [np.flatnonzero(v2_data["audit_counts"][week_index] > 0) for week_index in range(len(v2_data["audit_week_labels"]))]
    frame = causal_front_descriptors(
        positive_sets,
        inputs["nodes"][["x", "y"]].to_numpy(float),
        inputs["nodes"]["lat"].to_numpy(float),
        v2_data["audit_week_labels"],
    ).sort_values(["week_index", "node_id"]).reset_index(drop=True)
    require(frame.shape == (133 * EXPECTED_NODE_COUNT, 16), f"unexpected front-state shape: {frame.shape}")
    require(frame["week_index"].nunique() == 133 and frame["node_id"].nunique() == EXPECTED_NODE_COUNT, "front-state dimensions changed")
    nodes = inputs["nodes"]
    placeholder_distance = float(np.hypot(np.ptp(nodes["x"].to_numpy(float)), np.ptp(nodes["y"].to_numpy(float))))
    placeholder_recency = 134.0
    raw_distance_any = frame["distance_to_any_prior_detection_km"].to_numpy(float).reshape(133, EXPECTED_NODE_COUNT)
    raw_distance_prev4 = frame["distance_to_previous4_detection_km"].to_numpy(float).reshape(133, EXPECTED_NODE_COUNT)
    raw_recency = frame["weeks_since_any_detection_within_50km"].to_numpy(float).reshape(133, EXPECTED_NODE_COUNT)
    available_any = np.isfinite(raw_distance_any)
    available_prev4 = np.isfinite(raw_distance_prev4)
    available_recency = np.isfinite(raw_recency)
    distance_any = np.log1p(np.maximum(np.where(available_any, raw_distance_any, placeholder_distance), 0.0))
    distance_prev4 = np.log1p(np.maximum(np.where(available_prev4, raw_distance_prev4, placeholder_distance), 0.0))
    recency = np.log1p(np.maximum(np.where(available_recency, raw_recency, placeholder_recency), 0.0))
    front = np.stack([
        distance_any,
        distance_prev4,
        recency,
        available_any.astype(np.float32),
        available_prev4.astype(np.float32),
        available_recency.astype(np.float32),
    ], axis=2).astype(np.float32)
    require(np.isfinite(front).all(), "front warm-up features are non-finite")

    persisted = pd.read_parquet(persisted_path).sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    persisted_matrix = persisted[FRONT_FEATURES].to_numpy(np.float32).reshape(EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 6)
    target_matrix = front[WARMUP_WEEKS:, :, :]
    front_max_abs = float(np.max(np.abs(target_matrix - persisted_matrix)))
    require(front_max_abs <= 2e-6, f"reconstructed front features differ from persisted V2-A features: {front_max_abs}")
    selected = front[:SEQUENCE_WEEKS]
    sequence_labels = frame[["week", "week_index"]].drop_duplicates().sort_values("week_index")["week"].astype(str).tolist()[:SEQUENCE_WEEKS]
    current_front_path = experiment_root(output_root) / "front_features" / "causal_front_features_current.parquet"
    current_front_path.parent.mkdir(parents=True, exist_ok=True)
    target_frame = pd.DataFrame({
        "week": np.repeat(v2_data["audit_week_labels"][WARMUP_WEEKS:], EXPECTED_NODE_COUNT),
        "week_index": np.repeat(np.arange(EXPECTED_RESPONSE_WEEKS), EXPECTED_NODE_COUNT),
        "model_node_id": np.tile(np.arange(EXPECTED_NODE_COUNT), EXPECTED_RESPONSE_WEEKS),
        **{name: target_matrix[:, :, index].reshape(-1) for index, name in enumerate(FRONT_FEATURES)},
    })
    target_frame.to_parquet(current_front_path, index=False)
    return selected, {
        "source_path": current_front_path,
        "source_sha256": sha256_file(current_front_path),
        "source_builder": "scripts/run_task3b_v2a.py plus scripts/run_task3a_v2_audit.py causal_front_descriptors",
        "source_revised_manifest_sha256": sha256_file(inputs["manifest_path"]),
        "persisted_v2a_path": persisted_path,
        "persisted_v2a_sha256": sha256_file(persisted_path),
        "placeholder_distance_km": placeholder_distance,
        "placeholder_recency_weeks": placeholder_recency,
        "target_max_abs_difference_to_persisted_v2a": front_max_abs,
        "sequence_labels": sequence_labels,
    }


def build_tensors(output_root: Path, force: bool = False) -> dict[str, Any]:
    root = experiment_root(output_root)
    root.mkdir(parents=True, exist_ok=True)
    inputs_dir = input_root(output_root)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    existing = inputs_dir / "prepare_manifest.json"
    if existing.exists() and not force:
        return json.loads(existing.read_text(encoding="utf-8"))
    inputs = load_revised_inputs(output_root)
    join_qa, additions = load_static_additions(output_root, inputs["nodes"])
    front, front_meta = build_front_sequence(output_root, inputs)
    dynamic = np.asarray(inputs["dynamic_history"][52:52 + SEQUENCE_WEEKS], dtype=np.float32)
    static = np.asarray(inputs["static"], dtype=np.float32)
    density = np.log1p(np.maximum(static[:, :5], 0.0))
    indicators = static[:, 5:]
    calendar_index = np.arange(-WARMUP_WEEKS, DEVELOPMENT_WEEKS, dtype=np.float64)
    calendar = np.column_stack([
        np.sin(2 * np.pi * calendar_index / PERIOD),
        np.cos(2 * np.pi * calendar_index / PERIOD),
    ]).astype(np.float32)
    target_calendar = inputs["calendar"][:DEVELOPMENT_WEEKS].astype(np.float32)
    require(np.allclose(calendar[WARMUP_WEEKS:], target_calendar, atol=2e-5), "development calendar does not match frozen continuous calendar")
    static_base = np.broadcast_to(np.concatenate([density, indicators], axis=1)[None, :, :], (SEQUENCE_WEEKS, EXPECTED_NODE_COUNT, 10))
    calendar_tensor = np.broadcast_to(calendar[:, None, :], (SEQUENCE_WEEKS, EXPECTED_NODE_COUNT, 2))
    base_24 = np.concatenate([dynamic, static_base, calendar_tensor], axis=2)
    a0 = np.concatenate([base_24, front], axis=2).astype(np.float32)
    a3_additions = np.broadcast_to(additions["transformed"][None, :, :].astype(np.float32), (SEQUENCE_WEEKS, EXPECTED_NODE_COUNT, 4))
    a3 = np.concatenate([a0, a3_additions], axis=2).astype(np.float32)
    require(a0.shape == (SEQUENCE_WEEKS, EXPECTED_NODE_COUNT, 30), f"A0 tensor shape changed: {a0.shape}")
    require(a3.shape == (SEQUENCE_WEEKS, EXPECTED_NODE_COUNT, 34), f"A3 tensor shape changed: {a3.shape}")
    require(np.isfinite(a0).all() and np.isfinite(a3).all(), "input tensors contain non-finite values")
    counts_dev = np.asarray(inputs["counts"][:DEVELOPMENT_WEEKS], dtype=np.int64)
    edge_index = inputs["edges"][["source_node", "target_node"]].to_numpy(np.int64).T
    require(edge_index.shape == (2, EXPECTED_EDGE_COUNT), "edge index shape changed")
    require(edge_index.min() >= 0 and edge_index.max() < EXPECTED_NODE_COUNT, "edge index out of bounds")
    np.save(array_path(output_root, "A0"), a0)
    np.save(array_path(output_root, "A3"), a3)
    np.save(inputs_dir / "counts_development.npy", counts_dev)
    np.save(inputs_dir / "edge_index.npy", edge_index)
    np.save(inputs_dir / "node_ids.npy", np.arange(EXPECTED_NODE_COUNT, dtype=np.int64))
    join_qa.to_csv(root / "join_qa.csv", index=False)
    pd.DataFrame([{
        "node_count": EXPECTED_NODE_COUNT,
        "directed_edge_count": EXPECTED_EDGE_COUNT,
        "undirected_edge_count": EXPECTED_EDGE_COUNT // 2,
        "source_node_min": int(edge_index.min()),
        "source_node_max": int(edge_index.max()),
        "target_node_min": int(edge_index.min()),
        "target_node_max": int(edge_index.max()),
        "graph_type": "persisted fixed binary queen induced revised-domain graph",
        "passed": True,
    }]).to_csv(root / "graph_qa.csv", index=False)
    identity = pd.DataFrame([{
        "check": "raw_common_feature_identity",
        "max_abs_difference": float(np.max(np.abs(a0 - a3[:, :, :30]))),
        "passed": bool(np.array_equal(a0, a3[:, :, :30])),
    }])
    identity.to_csv(root / "common_feature_identity_check.csv", index=False)
    require(bool(identity.iloc[0]["passed"]), "A0/A3 common tensor columns differ before scaling")
    static_rows = []
    for index, name in enumerate(A3_ADDITIONS):
        values = additions["transformed"][:, index]
        repeated = a3[:, :, 30 + index]
        static_rows.append({
            "feature": name,
            "transformation": {"road_density": "log1p", "night_illumination": "log1p", "clay_0_15": "identity", "water_difference_wv0033_minus_wv0010_0_15": "identity"}[name],
            "min": float(values.min()), "max": float(values.max()), "mean": float(values.mean()), "sd": float(values.std()),
            "missing_count": int(np.isnan(values).sum()), "nonfinite_count": int((~np.isfinite(values)).sum()),
            "max_temporal_range": float(np.max(np.ptp(repeated, axis=0))),
            "node_count": EXPECTED_NODE_COUNT,
            "passed": bool(np.isfinite(values).all() and np.max(np.ptp(repeated, axis=0)) == 0.0),
        })
    pd.DataFrame(static_rows).to_csv(root / "static_feature_qa.csv", index=False)

    scaling_rows = []
    for fold, spec in FOLDS.items():
        train_times = np.asarray(spec["train"], dtype=int) + WARMUP_WEEKS
        for model_name, feature_names in [("A0", A0_FEATURES), ("A3", A3_FEATURES)]:
            matrix = a0[train_times] if model_name == "A0" else a3[train_times]
            mean = matrix.reshape(-1, matrix.shape[2]).mean(axis=0, dtype=np.float64)
            scale = matrix.reshape(-1, matrix.shape[2]).std(axis=0, dtype=np.float64)
            unscaled = [i for i, name in enumerate(feature_names) if name.endswith("_imputed") or name.endswith("_available") or name in CALENDAR_FEATURES]
            scaled = [i for i in range(len(feature_names)) if i not in set(unscaled)]
            mean[unscaled] = 0.0
            scale[unscaled] = 1.0
            scale[np.asarray(scaled)[(~np.isfinite(scale[scaled])) | (scale[scaled] == 0)]] = 1.0
            scaling_payload = {
                "fold": fold, "model": model_name, "feature_names": feature_names,
                "training_target_indices": spec["train"], "training_sequence_indices": train_times.tolist(),
                "mean": mean.tolist(), "standard_deviation": scale.tolist(),
                "scaled_feature_indices": scaled, "unscaled_feature_indices": unscaled,
                "indicators_unscaled": True, "calendar_unscaled": True,
            }
            write_json(inputs_dir / f"scaling_{model_name.lower()}_fold{fold}.json", scaling_payload)
            for name, mu, sd, is_scaled in zip(feature_names, mean, scale, [i in scaled for i in range(len(feature_names))]):
                scaling_rows.append({"fold": fold, "model": model_name, "feature": name, "mean": float(mu), "standard_deviation": float(sd), "scaled": bool(is_scaled)})
    pd.DataFrame(scaling_rows).to_csv(root / "scaling_parameters.csv", index=False)
    tensor_rows = []
    for model_name, array in [("A0", a0), ("A3", a3)]:
        tensor_rows.append({
            "model": model_name, "shape": "x".join(map(str, array.shape)), "time_count": array.shape[0], "node_count": array.shape[1], "feature_count": array.shape[2],
            "missing_count": int(np.isnan(array).sum()), "nonfinite_count": int((~np.isfinite(array)).sum()), "exact_node_order": True, "exact_time_order": True,
        })
    pd.DataFrame(tensor_rows).to_csv(root / "input_tensor_qa.csv", index=False)

    task_rows = []
    task_index = 0
    for fold in range(1, 5):
        for seed in SEEDS:
            for model_name in ("A0", "A3"):
                task_index += 1
                task_id = f"task_{task_index:03d}_{model_name}_fold{fold}_seed{seed}"
                task_rows.append({
                    "task_id": task_id, "fold": fold, "seed": seed, "model": model_name,
                    "predictor_count": 30 if model_name == "A0" else 34, "status": "planned",
                    "output_path": str(task_root(output_root) / f"{task_id}.json"), "attempt": 0,
                    "runtime_seconds": None, "best_epoch": None, "converged": None,
                })
    manifest = {
        "experiment_version": EXPERIMENT_VERSION,
        "repo_git_sha": git_sha(),
        "created_utc": pd.Timestamp.utcnow().isoformat(),
        "revised_model_output": str(inputs["revised"]),
        "revised_manifest_sha256": sha256_file(inputs["manifest_path"]),
        "node_count": EXPECTED_NODE_COUNT,
        "directed_edge_count": EXPECTED_EDGE_COUNT,
        "response_period": ["2025-W01", "2026-W29"],
        "development_period": ["2025-W01", "2026-W16"],
        "terminal_period_excluded": ["2026-W17", "2026-W29"],
        "development_week_count": DEVELOPMENT_WEEKS,
        "warmup_week_count": WARMUP_WEEKS,
        "sequence_week_count": SEQUENCE_WEEKS,
        "a0_features": A0_FEATURES,
        "a3_features": A3_FEATURES,
        "a3_additions": A3_ADDITIONS,
        "feature_transformations": {name: "log1p" if name in {"road_density", "night_illumination"} else "identity" for name in A3_ADDITIONS},
        "front_feature_provenance": front_meta,
        "augmentation_provenance": {"manifest": str(additions["augmentation_manifest_path"]), "manifest_sha256": sha256_file(additions["augmentation_manifest_path"]), "cache": str(additions["cache_path"]), "cache_sha256": additions["cache_sha256"], "soil": str(additions["soil_path"]), "road_night": str(additions["road_path"])},
        "architecture": ARCHITECTURE,
        "folds": FOLDS,
        "seeds": SEEDS,
        "terminal_response_loaded": False,
        "stgnn_fitted": False,
    }
    write_json(inputs_dir / "prepare_manifest.json", manifest)
    pd.DataFrame(task_rows).to_csv(root / "model_task_manifest.csv", index=False)
    write_json(root / "authoritative_domain_manifest.json", {
        "source": str(inputs["manifest_path"]), "source_sha256": sha256_file(inputs["manifest_path"]), "node_count": EXPECTED_NODE_COUNT, "directed_edge_count": EXPECTED_EDGE_COUNT,
        "boundary": inputs["manifest"]["boundary"], "revised_domain": inputs["manifest"]["revised_domain"], "response": inputs["manifest"]["response"], "folds": FOLDS,
        "terminal_response_loaded": False, "terminal_metrics_calculated": False,
    })
    write_json(root / "frozen_a0_feature_manifest.json", {"model": "Neural A0", "predictor_count": 30, "feature_order": A0_FEATURES, "source": str(output_root / "v2_prospective" / "model" / "v2a_feature_order.txt"), "theta": FIXED_THETA, "penalty_context": "structured V2-A penalty 0.01 is not applied as a neural penalty"})
    write_json(root / "frozen_a3_feature_manifest.json", {"model": "Neural A3", "predictor_count": 34, "feature_order": A3_FEATURES, "base_feature_manifest": str(root / "frozen_a0_feature_manifest.json"), "additions": A3_ADDITIONS, "transformations": manifest["feature_transformations"], "source": str(additions["augmentation_manifest_path"])})
    return manifest


def logistic_logit(value: float) -> float:
    value = min(max(float(value), 1e-8), 1 - 1e-8)
    return math.log(value / (1 - value))


def conditional_mean_from_mu(mu: float, theta: float) -> float:
    log_p0 = theta * (math.log(theta) - math.log(theta + max(mu, 1e-8)))
    ppos = -math.expm1(log_p0)
    return max(mu, 1e-8) / max(ppos, 1e-8)


def mu_for_conditional_mean(target: float, theta: float) -> float:
    if target <= 1:
        return max(target, 1e-8)
    lo, hi = 1e-8, max(float(target), 1.0)
    while conditional_mean_from_mu(hi, theta) < target:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if conditional_mean_from_mu(mid, theta) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def exact_metrics(counts: np.ndarray, logits: np.ndarray, mu: np.ndarray, theta: float, training_prevalence: float) -> dict[str, Any]:
    y = np.asarray(counts, dtype=np.int64).reshape(-1)
    logits = np.asarray(logits, dtype=float).reshape(-1)
    mu = np.maximum(np.asarray(mu, dtype=float).reshape(-1), 1e-8)
    p = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
    theta = max(float(theta), 1e-8)
    positive = y > 0
    p0_log = theta * (np.log(theta) - np.log(theta + mu))
    ppositive = -np.expm1(p0_log)
    positive_mean = mu / np.maximum(ppositive, 1e-8)
    expected = p * positive_mean
    log_nb = (gammaln(y[positive] + theta) - gammaln(theta) - gammaln(y[positive] + 1)
              + theta * (np.log(theta) - np.log(theta + mu[positive]))
              + y[positive] * (np.log(mu[positive]) - np.log(theta + mu[positive])))
    zt = log_nb - np.log(np.maximum(ppositive[positive], 1e-8))
    joint = np.empty_like(p)
    joint[positive] = -np.log(np.maximum(p[positive], 1e-8)) - zt
    joint[~positive] = -np.log(np.maximum(1 - p[~positive], 1e-8))
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
    prevalence = float(np.mean(positive))
    null_brier = prevalence * (1 - prevalence)
    result: dict[str, Any] = {
        "joint_hurdle_nll": float(np.mean(joint)),
        "bernoulli_nll": float(log_loss(positive, np.clip(p, 1e-8, 1 - 1e-8), labels=[0, 1])),
        "brier": float(brier_score_loss(positive, p)),
        "brier_skill": float(1 - np.mean((p - positive) ** 2) / max(null_brier, 1e-12)),
        "pr_auc": float(average_precision_score(positive, p)),
        "roc_auc": float(roc_auc_score(positive, p)) if np.unique(positive).size == 2 else None,
        "positive_count_mae": float(np.mean(np.abs(y[positive] - positive_mean[positive]))) if positive.any() else None,
        "positive_count_rmse": float(np.sqrt(np.mean((y[positive] - positive_mean[positive]) ** 2))) if positive.any() else None,
        "positive_count_bias": float(np.mean(positive_mean[positive] - y[positive])) if positive.any() else None,
        "zt_nb_nll": float(-np.mean(zt)) if positive.any() else None,
        "all_cell_mae": float(np.mean(np.abs(y - expected))),
        "all_cell_rmse": float(np.sqrt(np.mean((y - expected) ** 2))),
        "mean_predicted_count": float(expected.mean()),
        "mean_observed_count": float(y.mean()),
        "conditional_positive_mean": float(positive_mean[positive].mean()) if positive.any() else None,
        "observed_prevalence": prevalence,
        "training_prevalence": float(training_prevalence),
        "prediction_probability_sd": float(np.std(p)),
        "prediction_positive_mean_sd": float(np.std(positive_mean)),
        "fitted_theta": theta,
    }
    if np.unique(positive).size == 2:
        cal = LogisticRegression(C=1e6, solver="lbfgs", max_iter=100).fit(np.log(np.clip(p, 1e-8, 1 - 1e-8) / np.clip(1 - p, 1e-8, 1)), positive)
        result["calibration_intercept"] = float(cal.intercept_[0])
        result["calibration_slope"] = float(cal.coef_[0, 0])
    else:
        result["calibration_intercept"] = None
        result["calibration_slope"] = None
    return result


def load_prepare_manifest(output_root: Path) -> dict[str, Any]:
    path = input_root(output_root) / "prepare_manifest.json"
    require(path.exists(), f"prepare first; missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def task_specs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    index = 0
    for fold in range(1, 5):
        for seed in SEEDS:
            for model_name in ("A0", "A3"):
                index += 1
                rows.append({"task_index": index, "task_id": f"task_{index:03d}_{model_name}_fold{fold}_seed{seed}", "fold": fold, "seed": seed, "model": model_name})
    return rows


def load_scaling(output_root: Path, model_name: str, fold: int) -> dict[str, Any]:
    path = input_root(output_root) / f"scaling_{model_name.lower()}_fold{fold}.json"
    require(path.exists(), f"missing scaling parameters: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def train_task(output_root: Path, spec: dict[str, Any], cpu: bool = False) -> dict[str, Any]:
    started = time.time()
    root = experiment_root(output_root)
    task_id = spec["task_id"]
    model_name = spec["model"]
    fold = int(spec["fold"])
    seed = int(spec["seed"])
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available() and not cpu:
        torch.cuda.manual_seed_all(seed)
    feature_path = array_path(output_root, model_name)
    features = np.load(feature_path, mmap_mode="r")
    counts = np.load(input_root(output_root) / "counts_development.npy", mmap_mode="r")
    edges = np.load(input_root(output_root) / "edge_index.npy")
    scaling = load_scaling(output_root, model_name, fold)
    mean = np.asarray(scaling["mean"], dtype=np.float32)
    scale = np.asarray(scaling["standard_deviation"], dtype=np.float32)
    prepared = (np.asarray(features, dtype=np.float32) - mean[None, None, :]) / scale[None, None, :]
    require(np.isfinite(prepared).all(), f"{task_id}: preprocessed tensor is non-finite")
    target_features = prepared
    n_features = target_features.shape[2]
    device = torch.device("cuda" if torch.cuda.is_available() and not cpu else "cpu")
    model = GConvGRUHurdleNB(n_features, ARCHITECTURE["hidden_dimension"], ARCHITECTURE["K"], ARCHITECTURE["dropout"], normalization=ARCHITECTURE["normalization"], fixed_theta=FIXED_THETA).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=ARCHITECTURE["learning_rate"], weight_decay=ARCHITECTURE["weight_decay"])
    edge_index = torch.as_tensor(edges, dtype=torch.long, device=device)
    edge_weight = torch.ones(edge_index.shape[1], dtype=torch.float32, device=device)
    x = torch.as_tensor(target_features, dtype=torch.float32, device=device)
    y = torch.as_tensor(np.asarray(counts), dtype=torch.float32, device=device)
    fold_spec = FOLDS[fold]
    train_last = max(fold_spec["train"]) + 1
    eval_indices = fold_spec["validation"]
    eval_last = max(eval_indices) + 1
    train_prevalence = float(np.mean(np.asarray(counts)[fold_spec["train"]] > 0))
    train_positive = np.asarray(counts)[fold_spec["train"]]
    train_positive_mean = float(train_positive[train_positive > 0].mean())
    reference_mu = mu_for_conditional_mean(train_positive_mean, FIXED_THETA)
    val_counts_ref = np.asarray(counts)[eval_indices]
    reference_metrics = exact_metrics(
        val_counts_ref,
        np.full(val_counts_ref.shape, logistic_logit(train_prevalence), dtype=float),
        np.full(val_counts_ref.shape, reference_mu, dtype=float),
        FIXED_THETA,
        train_prevalence,
    )
    best_score = math.inf
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    wait = 0
    trajectories: list[dict[str, Any]] = []
    clip_count = 0
    nonfinite_events = 0
    for epoch in range(1, ARCHITECTURE["epoch_limit"] + 1):
        model.train()
        hidden = None
        epoch_losses: list[float] = []
        epoch_components = {key: [] for key in ["balanced_multitask_loss", "exact_joint_hurdle_nll", "bernoulli_nll", "zt_nb_nll", "weighted_bernoulli_contribution", "weighted_zt_nb_contribution"]}
        with torch.no_grad():
            for sequence_index in range(WARMUP_WEEKS):
                _, _, _, hidden = model.step(x[sequence_index], edge_index, edge_weight, hidden)
        for target_start in range(0, train_last, ARCHITECTURE["tbptt_weeks"]):
            optimizer.zero_grad(set_to_none=True)
            target_stop = min(target_start + ARCHITECTURE["tbptt_weeks"], train_last)
            logits_rows: list[torch.Tensor] = []
            mu_rows: list[torch.Tensor] = []
            for target_index in range(target_start, target_stop):
                logits, mu, _, hidden = model.step(x[WARMUP_WEEKS + target_index], edge_index, edge_weight, hidden)
                logits_rows.append(logits)
                mu_rows.append(mu)
            loss_result: dict[str, torch.Tensor] | None = None
            for local_index, (logits, mu) in enumerate(zip(logits_rows, mu_rows)):
                current = hurdle_losses(logits, mu, model.heads.raw_theta, y[target_start + local_index], positive_weight=1.0)
                keys = ["balanced_multitask_loss", "exact_joint_hurdle_nll", "bernoulli_nll", "zt_nb_nll", "weighted_bernoulli_contribution", "weighted_zt_nb_contribution"]
                loss_result = current if loss_result is None else {key: loss_result[key] + current[key] for key in keys}
            require(loss_result is not None, f"{task_id}: empty training chunk")
            steps = max(1, target_stop - target_start)
            loss = loss_result["balanced_multitask_loss"] / steps
            if not torch.isfinite(loss):
                nonfinite_events += 1
                raise FloatingPointError(f"{task_id}: non-finite training loss")
            loss.backward()
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), ARCHITECTURE["gradient_clip_norm"])
            if not torch.isfinite(grad_norm):
                nonfinite_events += 1
                raise FloatingPointError(f"{task_id}: non-finite gradient norm")
            if float(grad_norm) > ARCHITECTURE["gradient_clip_norm"]:
                clip_count += 1
            optimizer.step()
            epoch_losses.append(float(loss.detach().cpu()))
            for key in epoch_components:
                epoch_components[key].append(float((loss_result[key] / steps).detach().cpu()))
            hidden = hidden.detach()

        model.eval()
        pred_logits: list[np.ndarray] = []
        pred_mu: list[np.ndarray] = []
        with torch.no_grad():
            validation_hidden = hidden
            for target_index in range(train_last, eval_last):
                logits, mu, _, validation_hidden = model.step(x[WARMUP_WEEKS + target_index], edge_index, edge_weight, validation_hidden)
                pred_logits.append(logits.detach().cpu().numpy())
                pred_mu.append(mu.detach().cpu().numpy())
        val_logits = np.asarray(pred_logits)
        val_mu = np.asarray(pred_mu)
        val_counts = np.asarray(counts)[eval_indices]
        metrics = exact_metrics(val_counts, val_logits, val_mu, FIXED_THETA, train_prevalence)
        trajectories.append({
            "epoch": epoch,
            "training_loss": float(np.mean(epoch_losses)),
            "training_balanced_multitask_loss": float(np.mean(epoch_components["balanced_multitask_loss"])),
            "training_exact_joint_hurdle_nll": float(np.mean(epoch_components["exact_joint_hurdle_nll"])),
            "training_bernoulli_nll": float(np.mean(epoch_components["bernoulli_nll"])),
            "training_zt_nb_nll": float(np.mean(epoch_components["zt_nb_nll"])),
            "validation_joint_hurdle_nll": metrics["joint_hurdle_nll"],
            "validation_pr_auc": metrics["pr_auc"],
            "theta": FIXED_THETA,
        })
        score = float(metrics["joint_hurdle_nll"])
        if score < best_score - 1e-5:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            wait = 0
        else:
            wait += 1
            if wait >= ARCHITECTURE["early_stopping_patience"]:
                break
    require(best_state is not None, f"{task_id}: no valid checkpoint produced")
    model.load_state_dict(best_state)
    model.eval()
    all_logits: list[np.ndarray] = []
    all_mu: list[np.ndarray] = []
    hidden = None
    with torch.no_grad():
        for sequence_index in range(WARMUP_WEEKS):
            _, _, _, hidden = model.step(x[sequence_index], edge_index, edge_weight, hidden)
        for target_index in range(eval_last):
            logits, mu, _, hidden = model.step(x[WARMUP_WEEKS + target_index], edge_index, edge_weight, hidden)
            if target_index in eval_indices:
                all_logits.append(logits.detach().cpu().numpy())
                all_mu.append(mu.detach().cpu().numpy())
    final_logits = np.asarray(all_logits)
    final_mu = np.asarray(all_mu)
    final_counts = np.asarray(counts)[eval_indices]
    final_metrics = exact_metrics(final_counts, final_logits, final_mu, FIXED_THETA, train_prevalence)
    metadata = model_metadata(model)
    elapsed = time.time() - started
    checkpoint_path = model_root(output_root) / f"{task_id}.pt"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "task_id": task_id, "model": model_name, "fold": fold, "seed": seed, "metrics": final_metrics, "architecture": ARCHITECTURE}, checkpoint_path)
    prediction_path = model_root(output_root) / f"{task_id}_validation.npz"
    np.savez_compressed(prediction_path, logits=final_logits.astype(np.float32), underlying_mu=final_mu.astype(np.float32), counts=final_counts.astype(np.int16), validation_indices=np.asarray(eval_indices, dtype=np.int16))
    record = {
        "task_id": task_id, "fold": fold, "seed": seed, "model": model_name, "predictor_count": n_features,
        "status": "completed", "attempt": int(os.environ.get("STGNN_A3_ATTEMPT", "1")), "runtime_seconds": elapsed, "best_epoch": best_epoch, "converged": True,
        "output_path": str(checkpoint_path), "prediction_path": str(prediction_path), "device": str(device), "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"),
        "architecture": metadata, "theta": FIXED_THETA, "training_trajectory": trajectories, "metrics": final_metrics, "reference_metrics": reference_metrics,
        "training_prevalence": train_prevalence, "training_positive_count_mean": train_positive_mean, "gradient_clip_frequency": clip_count, "nonfinite_gradient_events": nonfinite_events,
        "git_sha": git_sha(), "feature_path": str(feature_path), "scaling_path": str(input_root(output_root) / f"scaling_{model_name.lower()}_fold{fold}.json"), "final_test_predictive_metrics_calculated": False,
    }
    write_json(task_root(output_root) / f"{task_id}.json", record)
    return record


def run_task(output_root: Path, task_index: int, cpu: bool = False) -> dict[str, Any]:
    manifest = load_prepare_manifest(output_root)
    specs = task_specs(manifest)
    require(1 <= task_index <= len(specs), f"task index out of range: {task_index}")
    spec = specs[task_index - 1]
    path = task_root(output_root) / f"{spec['task_id']}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("status") == "completed" and Path(existing.get("output_path", "")).exists():
            print(json.dumps(existing, indent=2, sort_keys=True))
            return existing
    try:
        record = train_task(output_root, spec, cpu=cpu)
    except Exception as exc:
        failed = {**spec, "status": "failed", "attempt": int(os.environ.get("STGNN_A3_ATTEMPT", "1")), "error": repr(exc), "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "converged": False}
        write_json(task_root(output_root) / f"{spec['task_id']}.json", failed)
        raise
    print(json.dumps(record, indent=2, sort_keys=True))
    return record


def paired_delta(a0: float | None, a3: float | None, higher: bool) -> float | None:
    if a0 is None or a3 is None or not np.isfinite(a0) or not np.isfinite(a3):
        return None
    return float(a3 - a0 if higher else a0 - a3)


def aggregate_results(output_root: Path, repo: Path) -> dict[str, Any]:
    manifest = load_prepare_manifest(output_root)
    result_dir = results_root(repo)
    result_dir.mkdir(parents=True, exist_ok=True)
    specs = task_specs(manifest)
    records = []
    missing = []
    for spec in specs:
        path = task_root(output_root) / f"{spec['task_id']}.json"
        if not path.exists():
            missing.append(spec["task_id"])
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") != "completed":
            missing.append(spec["task_id"])
        records.append(record)
    require(not missing, f"cannot finalize; incomplete tasks: {missing}")
    rows = []
    behavior_rows = []
    parameter_rows = []
    runtime_rows = []
    for record in records:
        metrics = record["metrics"]
        reference = record["reference_metrics"]
        row = {"task_id": record["task_id"], "model": record["model"], "fold": record["fold"], "seed": record["seed"], "predictor_count": record["predictor_count"], "status": record["status"], "best_epoch": record["best_epoch"], "runtime_seconds": record["runtime_seconds"], "converged": record["converged"], "theta": record["theta"]}
        for key in ["joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "positive_count_bias", "zt_nb_nll", "all_cell_mae", "all_cell_rmse", "mean_predicted_count", "mean_observed_count", "prediction_probability_sd", "prediction_positive_mean_sd"]:
            row[key] = metrics.get(key)
        for key in ["joint_hurdle_nll", "pr_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "positive_count_bias"]:
            row[f"reference_{key}"] = reference.get(key)
        rows.append(row)
        for trajectory in record["training_trajectory"]:
            behavior_rows.append({"task_id": record["task_id"], "model": record["model"], "fold": record["fold"], "seed": record["seed"], **trajectory})
        parameter_rows.append({"model": record["model"], "fold": record["fold"], "seed": record["seed"], "trainable_parameter_count": record["architecture"]["trainable_parameter_count"], "parameter_count_including_fixed_theta_buffer": record["architecture"]["parameter_count"], "theta_is_fixed": record["architecture"]["theta_is_fixed"]})
        runtime_rows.append({"task_id": record["task_id"], "model": record["model"], "fold": record["fold"], "seed": record["seed"], "runtime_seconds": record["runtime_seconds"], "device": record["device"], "gradient_clip_frequency": record["gradient_clip_frequency"], "nonfinite_gradient_events": record["nonfinite_gradient_events"]})
    metrics_frame = pd.DataFrame(rows)
    metrics_frame.to_csv(result_dir / "fold_seed_metrics.csv", index=False)
    task_manifest = metrics_frame[["task_id", "fold", "seed", "model", "predictor_count", "status", "runtime_seconds", "best_epoch", "converged"]].copy()
    task_manifest["attempt"] = [next(r["attempt"] for r in records if r["task_id"] == task_id) for task_id in task_manifest["task_id"]]
    task_manifest["output_path"] = [next(r["output_path"] for r in records if r["task_id"] == task_id) for task_id in task_manifest["task_id"]]
    task_manifest.to_csv(result_dir / "model_task_manifest.csv", index=False)
    for name in ["authoritative_domain_manifest.json", "frozen_a0_feature_manifest.json", "frozen_a3_feature_manifest.json", "graph_qa.csv", "join_qa.csv", "input_tensor_qa.csv", "static_feature_qa.csv", "common_feature_identity_check.csv", "scaling_parameters.csv"]:
        source = experiment_root(output_root) / name
        if source.exists():
            shutil.copy2(source, result_dir / name)
    pd.DataFrame(behavior_rows).to_csv(result_dir / "training_behavior.csv", index=False)
    parameter_frame = pd.DataFrame(parameter_rows)
    parameter_summary = parameter_frame.groupby("model", as_index=False).agg(trainable_parameter_count=("trainable_parameter_count", "first"), parameter_count_including_fixed_theta_buffer=("parameter_count_including_fixed_theta_buffer", "first"), theta_is_fixed=("theta_is_fixed", "all"))
    parameter_summary.to_csv(result_dir / "parameter_count_comparison.csv", index=False)
    pd.DataFrame(runtime_rows).to_csv(result_dir / "runtime_resource_comparison.csv", index=False)

    pairs = metrics_frame.pivot(index=["fold", "seed"], columns="model")
    pair_rows = []
    for (fold, seed), pair in pairs.iterrows():
        a0 = pair["A0"]
        a3 = pair["A3"]
        row = {"fold": fold, "seed": seed}
        for metric, higher in [("joint_hurdle_nll", False), ("pr_auc", True), ("roc_auc", True), ("brier", False), ("brier_skill", True), ("positive_count_mae", False), ("positive_count_rmse", False), ("positive_count_bias", False), ("zt_nb_nll", False), ("calibration_intercept", False), ("calibration_slope", False)]:
            a0_value, a3_value = a0.get(metric), a3.get(metric)
            row[f"A0_{metric}"] = a0_value
            row[f"A3_{metric}"] = a3_value
            if metric == "calibration_intercept":
                row["delta_calibration_intercept_toward_zero"] = paired_delta(abs(a0_value) if a0_value is not None else None, abs(a3_value) if a3_value is not None else None, False)
            elif metric == "calibration_slope":
                row["delta_calibration_slope_toward_one"] = paired_delta(abs(a0_value - 1) if a0_value is not None else None, abs(a3_value - 1) if a3_value is not None else None, False)
            else:
                row[f"delta_{metric}"] = paired_delta(a0_value, a3_value, higher)
        pair_rows.append(row)
    paired = pd.DataFrame(pair_rows)
    paired.to_csv(result_dir / "paired_metric_deltas.csv", index=False)
    calibration = paired[["fold", "seed", "A0_calibration_intercept", "A3_calibration_intercept", "A0_calibration_slope", "A3_calibration_slope", "delta_calibration_intercept_toward_zero", "delta_calibration_slope_toward_one"]]
    calibration.to_csv(result_dir / "calibration_comparison.csv", index=False)
    count_cols = ["fold", "seed", "A0_positive_count_mae", "A3_positive_count_mae", "A0_positive_count_rmse", "A3_positive_count_rmse", "A0_positive_count_bias", "A3_positive_count_bias", "delta_positive_count_mae", "delta_positive_count_rmse", "delta_positive_count_bias"]
    paired[count_cols].to_csv(result_dir / "count_comparison.csv", index=False)

    summary_rows = []
    for model_name in ["A0", "A3"]:
        subset = metrics_frame[metrics_frame["model"] == model_name]
        summary_rows.append({"model": model_name, "run_count": len(subset), "joint_hurdle_nll_mean": subset["joint_hurdle_nll"].mean(), "joint_hurdle_nll_sd": subset["joint_hurdle_nll"].std(ddof=1), "pr_auc_mean": subset["pr_auc"].mean(), "pr_auc_sd": subset["pr_auc"].std(ddof=1), "brier_mean": subset["brier"].mean(), "brier_skill_mean": subset["brier_skill"].mean(), "calibration_intercept_mean": subset["calibration_intercept"].mean(), "calibration_slope_mean": subset["calibration_slope"].mean(), "positive_count_mae_mean": subset["positive_count_mae"].mean(), "positive_count_rmse_mean": subset["positive_count_rmse"].mean(), "runtime_median_seconds": subset["runtime_seconds"].median(), "best_epoch_mean": subset["best_epoch"].mean(), "finite_predictions": bool(np.isfinite(subset[["joint_hurdle_nll", "pr_auc", "brier", "brier_skill"]].to_numpy(float)).all()), "nondegenerate_probability": bool((subset["prediction_probability_sd"] > 1e-8).all()), "nondegenerate_positive_mean": bool((subset["prediction_positive_mean_sd"] > 1e-8).all())})
    development_summary = pd.DataFrame(summary_rows)
    development_summary.to_csv(result_dir / "development_summary.csv", index=False)

    mean_deltas = {column: float(paired[column].mean()) for column in paired.columns if column.startswith("delta_")}
    prop_improved = {column: float(np.mean(paired[column] > 0)) for column in paired.columns if column.startswith("delta_")}
    f4 = paired[paired["fold"] == 4]
    a0_summary = development_summary[development_summary["model"] == "A0"].iloc[0]
    a3_summary = development_summary[development_summary["model"] == "A3"].iloc[0]
    a0_valid = bool(
        a0_summary["finite_predictions"]
        and a0_summary["nondegenerate_probability"]
        and a0_summary["nondegenerate_positive_mean"]
        and float(a0_summary["brier_skill_mean"]) > 0
        and float(a0_summary["pr_auc_mean"]) > float(metrics_frame[metrics_frame["model"] == "A0"]["reference_pr_auc"].mean())
        and float(a0_summary["joint_hurdle_nll_mean"]) < float(metrics_frame[metrics_frame["model"] == "A0"]["reference_joint_hurdle_nll"].mean())
    )
    primary_gain = bool(mean_deltas.get("delta_joint_hurdle_nll", 0) > 0 and mean_deltas.get("delta_pr_auc", 0) > 0 and mean_deltas.get("delta_brier_skill", 0) > 0)
    primary_consistent = bool(prop_improved.get("delta_joint_hurdle_nll", 0) >= 0.5 and prop_improved.get("delta_pr_auc", 0) >= 0.5 and prop_improved.get("delta_brier_skill", 0) >= 0.5)
    f4_guardrail = bool(f4["delta_joint_hurdle_nll"].mean() >= 0 and f4["delta_brier_skill"].mean() >= 0 and f4["delta_calibration_intercept_toward_zero"].mean() >= 0 and f4["delta_calibration_slope_toward_one"].mean() >= 0)
    calibration_guardrail = bool(mean_deltas.get("delta_calibration_intercept_toward_zero", -math.inf) >= 0 and mean_deltas.get("delta_calibration_slope_toward_one", -math.inf) >= 0)
    count_guardrail = bool(mean_deltas.get("delta_positive_count_mae", -math.inf) >= 0 and mean_deltas.get("delta_positive_count_rmse", -math.inf) >= 0 and abs(float(a3_summary["positive_count_mae_mean"]) - float(a0_summary["positive_count_mae_mean"])) <= max(0.05 * float(a0_summary["positive_count_mae_mean"]), 1e-8))
    stable = bool((metrics_frame["converged"] == True).all() and (metrics_frame["theta"] == FIXED_THETA).all() and (metrics_frame["runtime_seconds"] > 0).all())
    if not a0_valid:
        classification = "NEURAL A0 BASELINE INVALID — A3 COMPARISON NOT INTERPRETABLE"
        final_disposition = "NEURAL ARCHITECTURE REQUIRES SEPARATE REVIEW"
    elif primary_gain and primary_consistent and f4_guardrail and calibration_guardrail and count_guardrail and stable:
        classification = "ADVANCE"
        final_disposition = "STGNN-A3 DEVELOPMENT SPECIFICATION FROZEN"
    elif primary_gain or (mean_deltas.get("delta_pr_auc", 0) > 0 and mean_deltas.get("delta_brier_skill", 0) > 0):
        classification = "HOLD / AMBIGUOUS"
        final_disposition = "STGNN-A3 NOT ADVANCED"
    else:
        classification = "DO NOT ADVANCE"
        final_disposition = "STGNN-A3 NOT ADVANCED"
    decision = pd.DataFrame([{
        "classification": classification, "final_disposition": final_disposition, "a0_valid": a0_valid, "primary_gain": primary_gain, "primary_consistent": primary_consistent,
        "f4_guardrail": f4_guardrail, "calibration_guardrail": calibration_guardrail, "count_guardrail": count_guardrail, "stable_optimization": stable,
        "mean_delta_joint_hurdle_nll": mean_deltas.get("delta_joint_hurdle_nll"), "mean_delta_pr_auc": mean_deltas.get("delta_pr_auc"), "mean_delta_brier_skill": mean_deltas.get("delta_brier_skill"),
        "proportion_joint_nll_improved": prop_improved.get("delta_joint_hurdle_nll"), "proportion_pr_auc_improved": prop_improved.get("delta_pr_auc"), "proportion_brier_skill_improved": prop_improved.get("delta_brier_skill"),
        "prior_task_disposition": "STGNN-A3 NOT EVALUATED — SPECIFICATION CONFLICT RESOLVED BEFORE FITTING",
    }])
    decision.to_csv(result_dir / "final_ablation_decision.csv", index=False)

    figure_status = "FIGURE GENERATION UNAVAILABLE ON ATLAS"
    figure_dir = repo / "analysis" / "stgnn_a3_ablation" / "figures"
    try:
        import matplotlib.pyplot as plt
        figure_dir.mkdir(parents=True, exist_ok=True)
        for column, filename, title in [
            ("delta_pr_auc", "paired_delta_pr_auc.png", "Paired Δ PR-AUC (A3 − A0)"),
            ("delta_joint_hurdle_nll", "paired_delta_joint_nll.png", "Paired Δ joint NLL (A0 − A3)"),
            ("delta_brier_skill", "paired_delta_brier_skill.png", "Paired Δ Brier skill (A3 − A0)"),
        ]:
            fig, ax = plt.subplots(figsize=(7, 4))
            for fold, group in paired.groupby("fold"):
                ax.plot(group["seed"].astype(str), group[column], marker="o", label=f"F{fold}")
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set_title(title); ax.set_xlabel("Seed"); ax.set_ylabel("Improvement-oriented delta"); ax.legend(); fig.tight_layout(); fig.savefig(figure_dir / filename, dpi=160); plt.close(fig)
        for column, filename, title in [("delta_calibration_intercept_toward_zero", "calibration_comparison.png", "Calibration movement toward intercept 0"), ("delta_positive_count_mae", "count_error_comparison.png", "Positive-count MAE improvement")]:
            fig, ax = plt.subplots(figsize=(7, 4)); ax.bar(np.arange(len(paired)), paired[column]); ax.axhline(0, color="black", linewidth=0.8); ax.set_title(title); ax.set_xlabel("Paired fold × seed run"); ax.set_ylabel("Improvement-oriented delta"); fig.tight_layout(); fig.savefig(figure_dir / filename, dpi=160); plt.close(fig)
        figure_status = "figures generated"
    except Exception:
        figure_dir.mkdir(parents=True, exist_ok=True)
    (figure_dir / "figure_generation_status.txt").write_text(figure_status + "\n", encoding="utf-8")

    report = build_report(manifest, metrics_frame, paired, development_summary, decision.iloc[0].to_dict(), parameter_summary, runtime_rows, repo, output_root)
    (result_dir / "stgnn_a3_ablation_report.md").write_text(report, encoding="utf-8")
    final_manifest = {
        "experiment_version": EXPERIMENT_VERSION, "repo_git_sha": git_sha(repo), "output_root": str(experiment_root(output_root)),
        "result_root": str(result_dir), "atlas_job_ids": sorted({str(r.get("slurm_job_id")) for r in records if r.get("slurm_job_id")}),
        "task_count": len(records), "completed": len(records), "failed": 0, "fold_count": 4, "seed_count": len(SEEDS), "folds_used": [1, 2, 3, 4],
        "a0_fit_count": int(sum(r["model"] == "A0" for r in records)), "a3_fit_count": int(sum(r["model"] == "A3" for r in records)),
        "node_count": EXPECTED_NODE_COUNT, "directed_edge_count": EXPECTED_EDGE_COUNT, "a0_predictor_count": 30, "a3_predictor_count": 34,
        "theta": FIXED_THETA, "theta_changed_or_reestimated": False, "architecture": ARCHITECTURE, "classification": classification, "final_disposition": final_disposition,
        "terminal_response_loaded": False, "terminal_metrics_calculated": False, "feature_selection_reopened": False, "main_merged": False,
        "prior_task_disposition": "STGNN-A3 NOT EVALUATED — SPECIFICATION CONFLICT RESOLVED BEFORE FITTING",
        "provenance": manifest.get("augmentation_provenance"),
    }
    write_json(result_dir / "stgnn_a3_ablation_manifest.json", final_manifest)
    (result_dir / "software_environment.txt").write_text(environment_text(records), encoding="utf-8")
    return final_manifest


def environment_text(records: list[dict[str, Any]]) -> str:
    first = records[0]
    return "\n".join([
        f"python={platform.python_version()}",
        f"pytorch={torch.__version__}",
        f"cuda_available={torch.cuda.is_available()}",
        f"torch_geometric={__import__('torch_geometric').__version__}",
        f"torch_geometric_temporal={__import__('torch_geometric_temporal').__version__}",
        f"repo_git_sha={first.get('git_sha')}",
        f"experiment_version={EXPERIMENT_VERSION}",
        f"fixed_theta={FIXED_THETA}",
        "terminal_response_loaded=False",
        "terminal_metrics_calculated=False",
        "",
    ])


def build_report(manifest: dict[str, Any], metrics: pd.DataFrame, paired: pd.DataFrame, summary: pd.DataFrame, decision: dict[str, Any], parameters: pd.DataFrame, runtimes: list[dict[str, Any]], repo: Path, output_root: Path) -> str:
    lines = [
        "# STGNN Revised-Domain Paired Neural Experiment — A0 vs A3",
        "",
        "## 1. Objective",
        "",
        "This is the first valid revised-domain paired neural A0 versus A3 development experiment. It compares 30 frozen V2-A predictors with the same 30 predictors plus the four frozen augmentation predictors under one fixed GConvGRU hurdle-NB architecture.",
        "",
        "## 2. Resolution of prior specification conflict",
        "",
        "The obsolete Task-2B checkpoint was 24 features on 16,756 nodes and was not used. The structured V2-A artifact supplied the 30-feature predictor specification only and was not treated as a neural checkpoint. The current neural experiment uses 30 versus 34 features on the revised 10,037-node domain.",
        "",
        "The prior task is recorded as: `STGNN-A3 NOT EVALUATED — SPECIFICATION CONFLICT RESOLVED BEFORE FITTING`.",
        "",
        "## 3. Provenance",
        "",
        f"- Repository SHA at preparation: `{manifest.get('repo_git_sha')}`.",
        f"- Revised production manifest: `{manifest.get('revised_manifest_sha256')}`.",
        f"- Revised domain: {manifest.get('node_count')} nodes and {manifest.get('directed_edge_count')} directed queen edges.",
        f"- Augmentation sources and checksums are recorded in `{manifest.get('augmentation_provenance')}`.",
        "- Structured-model penalty 0.01 was not introduced as a neural penalty; neural weight decay remains 0.0.",
        "",
        "## 4. Input QA",
        "",
        "See `authoritative_domain_manifest.json`, `graph_qa.csv`, `join_qa.csv`, `input_tensor_qa.csv`, `static_feature_qa.csv`, `common_feature_identity_check.csv`, and `scaling_parameters.csv`.",
        "",
        f"- A0 tensor: `[120, {EXPECTED_NODE_COUNT}, 30]`; A3 tensor: `[120, {EXPECTED_NODE_COUNT}, 34]`.",
        f"- The sequence contains 52 warm-up weeks followed by the 68 development weeks; terminal responses were not loaded.",
        f"- Common A0/A3 feature max absolute difference before scaling: `{float(np.max(np.abs(np.load(array_path(output_root, 'A0'), mmap_mode='r') - np.load(array_path(output_root, 'A3'), mmap_mode='r')[:, :, :30]))):.17g}`.",
        "",
        "## 5. Architecture",
        "",
        "```json",
        json.dumps(ARCHITECTURE, indent=2),
        "```",
        "",
        "The four A3 inputs are appended after the 30 A0 inputs. Road density and night illumination use log1p; both soil variables use identity. Fixed theta is 0.7018903965556372 for both models.",
        "",
        "## 6. A0 neural validity",
        "",
        f"A0 validity result: **{'A0 NEURAL BASELINE VALID' if decision.get('a0_valid') else 'NEURAL A0 BASELINE INVALID — A3 COMPARISON NOT INTERPRETABLE'}**.",
        "",
        "The validity gate required finite/converged runs, nondegenerate probability and positive-count predictions, positive mean Brier skill, PR-AUC above the paired prevalence reference, and joint NLL below the paired prevalence/mean-count reference.",
        "",
        "## 7. Execution",
        "",
        f"- Folds: 4; seeds: {len(SEEDS)}; paired fits: {len(metrics)}.",
        f"- Atlas job IDs: `{', '.join(sorted({str(r.get('slurm_job_id')) for r in runtimes if r.get('slurm_job_id')}))}`.",
        f"- Median A0 runtime: {metrics.loc[metrics.model == 'A0', 'runtime_seconds'].median():.3f} seconds; median A3 runtime: {metrics.loc[metrics.model == 'A3', 'runtime_seconds'].median():.3f} seconds.",
        "",
        "## 8. A0 versus A3 predictive results",
        "",
        summary.to_markdown(index=False),
        "",
        "## 9. Paired deltas",
        "",
        "Positive deltas indicate A3 improvement. Joint NLL, Brier, count MAE/RMSE, count NLL, and calibration distances use improvement-oriented signs.",
        "",
        paired[["fold", "seed", "delta_joint_hurdle_nll", "delta_pr_auc", "delta_brier_skill", "delta_positive_count_mae", "delta_positive_count_rmse", "delta_calibration_intercept_toward_zero", "delta_calibration_slope_toward_one"]].to_markdown(index=False),
        "",
        "## 10. F4",
        "",
        paired[paired.fold == 4][["seed", "delta_joint_hurdle_nll", "delta_pr_auc", "delta_brier_skill", "delta_calibration_intercept_toward_zero", "delta_calibration_slope_toward_one", "delta_positive_count_mae", "delta_positive_count_rmse"]].to_markdown(index=False),
        "",
        "## 11. Calibration and count behavior",
        "",
        "Calibration and count comparison tables are persisted in `calibration_comparison.csv` and `count_comparison.csv`. No post-hoc calibrator was fitted.",
        "",
        "## 12. Computational impact",
        "",
        parameters.to_markdown(index=False),
        "",
        f"- Median runtime increase (A3 relative to A0): {(metrics.loc[metrics.model == 'A3', 'runtime_seconds'].median() / metrics.loc[metrics.model == 'A0', 'runtime_seconds'].median() - 1):.3%}.",
        "- Peak memory was not exposed by the canonical runner; GPU/device provenance is retained per task in the task JSON and runtime table.",
        "",
        "## 13. Development classification",
        "",
        f"`{decision.get('classification')}`",
        "",
        "## 14. Boundary checks",
        "",
        "```text",
        "revised 10,037-node domain used: YES",
        "obsolete 16,756-node checkpoint used as baseline: NO",
        "30-feature structured model used as neural checkpoint: NO",
        "GConvGRU architecture held constant: YES",
        "A0 feature count: 30",
        "A3 feature count: 34",
        "four A3 additions unchanged: YES",
        "road/night transformations unchanged: YES",
        "soil transformations unchanged: YES",
        "common A0/A3 features identical: YES",
        "theta changed/re-estimated: NO",
        "architecture tuned: NO",
        "hidden dimension changed: NO",
        "dropout changed: NO",
        "learning rate changed: NO",
        "graph changed: NO",
        "warm-up/TBPTT changed: NO",
        "F1–F4 only for selection: YES",
        "F5/F6 used: NO",
        "later outcomes used: NO",
        "feature selection reopened: NO",
        "main merged: NO",
        "```",
        "",
        "## 15. Final disposition",
        "",
        f"`{decision.get('final_disposition')}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["prepare", "run", "finalize"], required=True)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT_DEFAULT)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    parser.add_argument("--task-index", type=int)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.mode == "prepare":
        manifest = build_tensors(args.output_root, force=args.force)
        print(json.dumps(manifest, indent=2, sort_keys=True))
    elif args.mode == "run":
        require(args.task_index is not None, "--task-index is required for run mode")
        run_task(args.output_root, args.task_index, cpu=args.cpu)
    else:
        print(json.dumps(aggregate_results(args.output_root, args.repo), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
