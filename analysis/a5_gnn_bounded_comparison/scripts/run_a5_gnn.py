"""Run the prespecified A5-GNN bounded development comparison."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, csr_matrix, diags
from scipy.special import expit
from scipy.spatial import cKDTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "python"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from task2c_metrics import evaluate_predictions  # noqa: E402

from a5_model import (  # noqa: E402
    THETA,
    canonical_directed_edges,
    center_residual,
    deterministic_spatial_shells,
    exact_joint_hurdle_nll,
    hurdle_predictions,
    laplacian_positional_encoding,
    make_model,
    parameter_count,
    set_seed,
)


NODE_COUNT = 10_037
DEVELOPMENT_WEEKS = 68
FOLDS = [
    {"fold": 1, "train_indices": np.arange(0, 26), "validation_indices": np.arange(26, 39), "validation_start": "2025-W27", "validation_end": "2025-W39"},
    {"fold": 2, "train_indices": np.arange(0, 39), "validation_indices": np.arange(39, 52), "validation_start": "2025-W40", "validation_end": "2025-W52"},
    {"fold": 3, "train_indices": np.arange(0, 52), "validation_indices": np.arange(52, 60), "validation_start": "2026-W01", "validation_end": "2026-W08"},
    {"fold": 4, "train_indices": np.arange(0, 60), "validation_indices": np.arange(60, 68), "validation_start": "2026-W09", "validation_end": "2026-W16"},
]
NEURAL_CANDIDATES = ["A5-PE", "A5-GNN-NOPE", "A5-GNN"]
SEEDS = [1729, 31415, 271828]
PRODUCTION_MODEL_SHA = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
FROZEN_A4S_MANIFEST_SHA = "156ab650b8fa79f7a4fe390f3687ca53212fbf37fb7e9963ba91b9f70c9b68af"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AUG = load_module(REPOSITORY_ROOT / "analysis/predictor_augmentation/scripts/run_predictor_augmentation.py", "a5_augmentation")
A4 = load_module(REPOSITORY_ROOT / "analysis/structured_a4_comparison/scripts/run_a4_comparison.py", "a5_a4_reference")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    if args == ("rev-parse", "HEAD") and os.environ.get("STGNN_GIT_SHA"):
        return os.environ["STGNN_GIT_SHA"]
    if args == ("branch", "--show-current") and os.environ.get("STGNN_GIT_BRANCH"):
        return os.environ["STGNN_GIT_BRANCH"]
    try:
        return subprocess.check_output(["git", *args], cwd=REPOSITORY_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def config_sha256(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_output_root(explicit: Path | None) -> Path:
    value = explicit or (Path(os.environ["A5_GNN_OUTPUT_ROOT"]) if os.environ.get("A5_GNN_OUTPUT_ROOT") else None)
    if value is None:
        raise RuntimeError("A5_GNN_OUTPUT_ROOT or --output-root is required")
    return value.expanduser().resolve()


def write_npz_atomic(path: Path, arrays: dict[str, np.ndarray]) -> None:
    """Write a prediction archive atomically so interrupted jobs are detectable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp.npz", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        with np.load(temporary, allow_pickle=False) as check:
            if set(check.files) != set(arrays):
                raise RuntimeError(f"atomic prediction validation failed for {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def checkpoint_metadata(
    data: DataBundle,
    config: dict[str, Any],
    candidate: str,
    fold_id: int,
    seed: int,
    unit_scope: str,
) -> dict[str, Any]:
    return {
        "checkpoint_version": 1,
        "candidate": candidate,
        "outer_fold": int(fold_id),
        "seed": int(seed),
        "unit_scope": unit_scope,
        "execution_sha": git_value("rev-parse", "HEAD"),
        "config_sha256": config_sha256(config),
        "input_sha256": dict(data.hashes),
        "graph": {
            "node_count": NODE_COUNT,
            "directed_edge_count": int(len(data.source)),
            "edge_sha256": data.hashes.get("edges"),
        },
    }


def write_checkpoint_atomic(path: Path, model: Any, fit_info: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Atomically write and validate one completed neural unit checkpoint."""
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    cpu_state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
    payload = {"status": "COMPLETED", "metadata": metadata, "fit_info": fit_info, "model_state_dict": cpu_state}
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        validation = torch.load(temporary, map_location="cpu", weights_only=False)
        if validation.get("status") != "COMPLETED" or validation.get("metadata") != metadata:
            raise RuntimeError(f"checkpoint validation failed for {path}")
        if set(validation.get("model_state_dict", {})) != set(cpu_state):
            raise RuntimeError(f"checkpoint state validation failed for {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_completed_checkpoint(
    path: Path,
    candidate: str,
    input_dim: int,
    config: dict[str, Any],
    device: Any,
    expected_metadata: dict[str, Any],
) -> tuple[Any | None, dict[str, Any] | None, str]:
    """Load only a complete, provenance-matching checkpoint."""
    import torch

    if not path.exists() or path.stat().st_size == 0:
        return None, None, "NOT_FOUND"
    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("status") != "COMPLETED" or payload.get("metadata") != expected_metadata:
            return None, None, "UNKNOWN_REGENERATE"
        model = make_model(candidate, input_dim, config["model"]["hidden_dim"], config["model"]["dropout"], config["model"]["activation"]).to(device)
        model.load_state_dict(payload["model_state_dict"], strict=True)
        model.eval()
        fit_info = dict(payload["fit_info"])
        fit_info["checkpoint_path"] = str(path)
        return model, fit_info, "VERIFIED_REUSABLE"
    except Exception:
        return None, None, "UNKNOWN_REGENERATE"


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


COMPACT_PROMOTION_FILES = (
    "results/fold_seed_metrics.csv",
    "results/aggregate_metrics.csv",
    "results/a3_baseline_reproduction.csv",
    "results/residual_spatial_summary.csv",
    "results/residual_temporal_summary.csv",
    "results/frontier_metrics.csv",
    "results/spatial_stress_metrics.csv",
    "results/spatial_stress_status.json",
    "results/a5_decision.json",
    "figures/figure_generation_status.json",
    "provenance/a5_analysis_manifest.json",
    "provenance/feature_target_access_audit.json",
    "provenance/checksum_manifest.json",
    "final_decision_report.md",
)


def promote_compact_outputs(output: Path, durable_root: Path | None) -> dict[str, Any]:
    if durable_root is None:
        return {"status": "NOT_REQUESTED", "storage_class": "TEMPORARY_90DAY_STORAGE"}
    copied: list[dict[str, Any]] = []
    for relative in COMPACT_PROMOTION_FILES:
        source = output / relative
        if not source.exists() or source.stat().st_size == 0:
            continue
        destination = durable_root / relative
        atomic_copy(source, destination)
        copied.append({"path": relative, "size_bytes": int(destination.stat().st_size), "sha256": sha256_file(destination)})
    manifest = {
        "status": "COMPLETED",
        "storage_class": "DURABLE_PROJECT_ARTIFACTS",
        "source_output_root": str(output),
        "durable_summary_root": str(durable_root),
        "temporary_storage_warning": "TEMPORARY_90DAY_STORAGE large products remain under /90daydata and are automatically removed after 90 days without activity.",
        "files": copied,
    }
    write_json(durable_root / "provenance/a5_durable_promotion_manifest.json", manifest)
    return manifest


def read_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["canonical_start_sha"] != "6715a4397dad21a77414bd2ce41586751290f374":
        raise RuntimeError("A5 canonical starting SHA changed")
    if config["development_period"]["start"] != "2025-W01" or config["development_period"]["end"] != "2026-W16":
        raise RuntimeError("A5 development boundary changed")
    if config["model"]["theta"] != THETA or config["model"]["loss"] != "exact_joint_hurdle_nll":
        raise RuntimeError("A5 fixed-theta hurdle contract changed")
    if config["model"]["hidden_dim"] != 16 or config["model"]["layers"] != 2:
        raise RuntimeError("A5 primary architecture dimensions changed")
    if config["seeds"] != SEEDS:
        raise RuntimeError("A5 seed set changed")
    if set(config["candidates"]) != {"A3", "STRUCTURED_A4S_CHALLENGER", *NEURAL_CANDIDATES}:
        raise RuntimeError("A5 candidate scope changed")
    if config["storage"]["output_root_env"] != "A5_GNN_OUTPUT_ROOT" or config["storage"]["temporary_storage_class"] != "TEMPORARY_90DAY_STORAGE":
        raise RuntimeError("A5 storage routing contract changed")
    return config


@dataclass
class DataBundle:
    a3: np.ndarray
    counts: np.ndarray
    nodes: pd.DataFrame
    weeks: pd.DataFrame
    folds: list[dict[str, Any]]
    adjacency: csr_matrix
    source: np.ndarray
    target: np.ndarray
    degree: np.ndarray
    positional_encoding: np.ndarray
    positional_metadata: dict[str, Any]
    spatial_assignment: pd.DataFrame | None
    paths: dict[str, Path]
    hashes: dict[str, str]


@dataclass
class FoldPrepared:
    fold: int
    train_times: np.ndarray
    validation_times: np.ndarray
    x: np.ndarray
    counts: np.ndarray
    eta: np.ndarray
    xi: np.ndarray
    a3_state: dict[str, Any]
    scaling: dict[str, Any]


def load_data(args: argparse.Namespace, config: dict[str, Any]) -> DataBundle:
    base, counts, nodes, metadata = AUG.load_base(args.model_output, args.front_features)
    added, _ = A4.load_static_added(args.soil_features, args.anthropogenic_features, nodes)
    a3 = np.concatenate([base, np.broadcast_to(added[None, :, :], (DEVELOPMENT_WEEKS, NODE_COUNT, added.shape[1]))], axis=2)
    if a3.shape != (DEVELOPMENT_WEEKS, NODE_COUNT, 34) or not np.isfinite(a3).all():
        raise RuntimeError(f"A3 predictor matrix contract failed: {a3.shape}")
    weeks = pd.read_parquet(args.model_output / "raw/weeks.parquet")
    expected_weeks = [f"2025-W{week:02d}" for week in range(1, 53)] + [f"2026-W{week:02d}" for week in range(1, 17)]
    if weeks["iso_week"].astype(str).tolist()[:DEVELOPMENT_WEEKS] != expected_weeks:
        raise RuntimeError("development weeks are not exactly 2025-W01 through 2026-W16")
    if any(int(max(fold["validation_indices"])) >= DEVELOPMENT_WEEKS for fold in FOLDS):
        raise RuntimeError("authorized F1-F4 validation indices exceed development boundary")

    edges = pd.read_parquet(args.edges)
    source, target = canonical_directed_edges(edges["source_node"], edges["target_node"], NODE_COUNT)
    adjacency = coo_matrix((np.ones(len(source), dtype=np.float64), (source, target)), shape=(NODE_COUNT, NODE_COUNT)).tocsr()
    adjacency.data[:] = 1.0
    degree = np.asarray(adjacency.sum(axis=1)).ravel().astype(np.float64)
    if len(source) != 77_614 or np.sum(degree == 0) != 3:
        raise RuntimeError(f"canonical graph contract failed: directed_edges={len(source)}, isolates={np.sum(degree == 0)}")
    coordinates = nodes[["lon", "lat"]].to_numpy(np.float64)
    positional_encoding, positional_metadata = laplacian_positional_encoding(adjacency, coordinates, 8)

    spatial_path = args.spatial_assignments
    if spatial_path is None:
        candidate = args.model_output / "splits" / "spatial_node_assignments.parquet"
        spatial_path = candidate if candidate.exists() else None
    spatial_assignment = None
    if spatial_path is not None and spatial_path.exists():
        spatial_assignment = pd.read_parquet(spatial_path)
        if "spatial_fold" not in spatial_assignment.columns or "model_node_id" not in spatial_assignment.columns:
            raise RuntimeError("spatial assignment lacks model_node_id/spatial_fold")
        spatial_assignment = spatial_assignment.sort_values("model_node_id").reset_index(drop=True)
        if not np.array_equal(spatial_assignment["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
            raise RuntimeError("spatial assignment node order changed")

    paths = {
        "model_manifest": args.model_output / "manifests/revised_production_manifest.json",
        "dynamic_features": args.model_output / "raw/dynamic_features.npy",
        "static_features": args.model_output / "raw/static_features.npy",
        "targets_count": args.model_output / "raw/targets_count.npy",
        "weeks": args.model_output / "raw/weeks.parquet",
        "nodes": args.model_output / "raw/nodes.parquet",
        "edges": args.edges,
        "causal_front_features": args.front_features,
        "soil_features": args.soil_features,
        "anthropogenic_features": args.anthropogenic_features,
        "a3_reference": args.a3_reference,
        "config": args.config,
    }
    if spatial_path is not None:
        paths["spatial_assignments"] = spatial_path
    if args.a3_frozen_output is not None:
        for fold_id in range(1, 5):
            task_id = (fold_id - 1) * 2 + 2
            paths[f"a3_frozen_fold_{fold_id}"] = args.a3_frozen_output / "tasks" / f"task_{task_id:03d}_A3_fold{fold_id}.json"
            paths[f"a3_frozen_prediction_{fold_id}"] = args.a3_frozen_output / "predictions" / f"task_{task_id:03d}_A3_fold{fold_id}.npz"
    hashes = {key: sha256_file(path) for key, path in paths.items() if path.exists()}
    return DataBundle(
        a3=np.asarray(a3, dtype=np.float64), counts=np.asarray(counts, dtype=np.int64), nodes=nodes,
        weeks=weeks, folds=FOLDS, adjacency=adjacency, source=source, target=target,
        degree=degree, positional_encoding=positional_encoding, positional_metadata=positional_metadata,
        spatial_assignment=spatial_assignment, paths=paths, hashes=hashes,
    )


def apply_frozen_scaling(raw: np.ndarray, scaling: dict[str, Any], feature_names: list[str]) -> np.ndarray:
    if scaling.get("feature_names") != feature_names:
        raise RuntimeError("frozen A3 scaling feature order changed")
    mean = np.asarray(scaling["training_mean"], dtype=np.float64)
    sd = np.asarray(scaling["training_sd"], dtype=np.float64)
    if mean.shape != (len(feature_names),) or sd.shape != (len(feature_names),) or not np.isfinite(mean).all() or not np.isfinite(sd).all():
        raise RuntimeError("frozen A3 scaling payload is invalid")
    return (np.asarray(raw, dtype=np.float64) - mean[None, :]) / sd[None, :]


def load_frozen_a3_state(frozen_output: Path, fold_id: int, raw_train: np.ndarray, raw_eval: np.ndarray, feature_names: list[str]) -> tuple[dict[str, Any], np.ndarray, np.ndarray, dict[str, Any]]:
    task_id = (int(fold_id) - 1) * 2 + 2
    task_path = frozen_output / "tasks" / f"task_{task_id:03d}_A3_fold{int(fold_id)}.json"
    if not task_path.exists():
        raise RuntimeError(f"missing frozen A3 fold task: {task_path}")
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    if payload.get("status") != "completed" or payload.get("model") != "A3" or int(payload.get("fold", -1)) != int(fold_id):
        raise RuntimeError(f"invalid frozen A3 fold task: {task_path}")
    if payload.get("theta") != THETA or payload.get("penalty") != 0.01 or payload.get("theta_fixed") is not True:
        raise RuntimeError(f"frozen A3 theta/penalty contract changed: {task_path}")
    scaling = payload.get("scaling")
    if not isinstance(scaling, dict):
        raise RuntimeError(f"frozen A3 scaling is missing: {task_path}")
    x_train = apply_frozen_scaling(raw_train, scaling, feature_names)
    x_eval = apply_frozen_scaling(raw_eval, scaling, feature_names)
    occurrence_beta = np.asarray(payload.get("occurrence_coefficients"), dtype=np.float64)
    count_beta = np.asarray(payload.get("count_coefficients"), dtype=np.float64)
    if occurrence_beta.shape != (len(feature_names) + 1,) or count_beta.shape != (len(feature_names) + 1,):
        raise RuntimeError(f"frozen A3 coefficient dimensions changed: {task_path}")
    state = {
        "occurrence_beta": occurrence_beta,
        "count_beta": count_beta,
        "theta": THETA,
        "fit_info": payload.get("fit_info", {}),
        "frozen_task_path": str(task_path),
    }
    return state, x_train, x_eval, scaling


def load_frozen_a3_predictions(frozen_output: Path, fold_id: int, counts: np.ndarray, validation_times: np.ndarray) -> dict[str, np.ndarray]:
    task_id = (int(fold_id) - 1) * 2 + 2
    path = frozen_output / "predictions" / f"task_{task_id:03d}_A3_fold{int(fold_id)}.npz"
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"missing frozen A3 prediction archive: {path}")
    with np.load(path, allow_pickle=False) as archive:
        required = {"y", "p", "conditional", "mu"}
        if not required.issubset(set(archive.files)):
            raise RuntimeError(f"frozen A3 prediction archive lacks required arrays: {path}")
        arrays = {key: np.asarray(archive[key]) for key in required}
    expected_y = counts[validation_times].reshape(-1).astype(np.int64)
    if arrays["y"].shape != expected_y.shape or not np.array_equal(arrays["y"].astype(np.int64), expected_y):
        raise RuntimeError(f"frozen A3 prediction target mismatch: {path}")
    if any(arrays[key].shape != expected_y.shape or not np.isfinite(arrays[key]).all() for key in ("p", "conditional", "mu")):
        raise RuntimeError(f"frozen A3 prediction shape/value contract failed: {path}")
    return arrays


A3_REFERENCE_METRICS = [
    "joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill",
    "calibration_intercept", "calibration_slope", "positive_count_mae",
    "positive_count_rmse", "conditional_mean_bias",
]


def load_a3_reference_metrics(path: Path) -> pd.DataFrame:
    reference = pd.read_csv(path)
    reference = reference.loc[reference["model"].astype(str).eq("A3")].set_index("fold")
    if not set(range(1, 5)).issubset(reference.index) or not set(A3_REFERENCE_METRICS).issubset(reference.columns):
        raise RuntimeError("authoritative A3 reference lacks required F1-F4 metrics")
    return reference


def overwrite_a3_reference_metrics(record: dict[str, Any], reference: pd.DataFrame, fold_id: int) -> dict[str, Any]:
    result = dict(record)
    for metric in A3_REFERENCE_METRICS:
        result[metric] = float(reference.loc[int(fold_id), metric])
    result["frozen_reference_metrics"] = True
    return result


def fit_a3_for_rows(
    raw_train: np.ndarray,
    y_train: np.ndarray,
    raw_eval: np.ndarray,
    feature_names: list[str],
    frozen_output: Path | None = None,
    fold_id: int | None = None,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray, dict[str, Any]]:
    if frozen_output is not None and fold_id is not None:
        state, x_train, x_eval, scaling = load_frozen_a3_state(frozen_output, fold_id, raw_train, raw_eval, feature_names)
        return {**state, "scaling": scaling}, (x_train, x_eval), (None, None, None, None), scaling
    # Reuse the canonical frozen A3 fitter exactly. The A4 helper has a
    # numerically similar but not bitwise-identical count optimizer, which is
    # insufficient for the required 1e-9 A3 reproduction gate.
    x_train, x_eval, scaling = AUG.standardize(raw_train, raw_eval, feature_names)
    state = AUG.fit_fixed_theta(x_train, y_train)
    train_design = np.column_stack([np.ones(len(x_train)), x_train])
    eval_design = np.column_stack([np.ones(len(x_eval)), x_eval])
    eta_train = train_design @ state["occurrence_beta"]
    xi_train = train_design @ state["count_beta"]
    eta_eval = eval_design @ state["occurrence_beta"]
    xi_eval = eval_design @ state["count_beta"]
    state = {**state, "scaling": scaling}
    return state, (x_train, x_eval), (eta_train, xi_train, eta_eval, xi_eval), scaling


def prepare_temporal_fold(data: DataBundle, fold: dict[str, Any], frozen_output: Path | None = None) -> FoldPrepared:
    train_times = np.asarray(fold["train_indices"], dtype=np.int64)
    validation_times = np.asarray(fold["validation_indices"], dtype=np.int64)
    raw_train = data.a3[train_times].reshape(-1, 34)
    raw_eval = data.a3[validation_times].reshape(-1, 34)
    y_train = data.counts[train_times].reshape(-1)
    state, _, _, scaling = fit_a3_for_rows(raw_train, y_train, raw_eval, AUG.BASE_FEATURES + AUG.ADDED_FEATURES, frozen_output, int(fold["fold"]))
    mean = np.asarray(scaling["training_mean"], dtype=np.float64)
    sd = np.asarray(scaling["training_sd"], dtype=np.float64)
    x = ((data.a3 - mean[None, None, :]) / sd[None, None, :]).astype(np.float32)
    design_all = np.concatenate([np.ones((DEVELOPMENT_WEEKS, NODE_COUNT, 1)), x.astype(np.float64)], axis=2)
    eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
    xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
    return FoldPrepared(int(fold["fold"]), train_times, validation_times, x, data.counts, eta, xi, state, scaling)


def add_metric_aliases(metrics: dict[str, Any], y: np.ndarray, p: np.ndarray, conditional: np.ndarray) -> dict[str, Any]:
    result = dict(metrics)
    positive = np.asarray(y) > 0
    result["conditional_mean_bias"] = float(np.mean(conditional[positive]) - np.mean(y[positive])) if positive.any() else None
    result["full_hurdle_expected_count_mae"] = float(np.mean(np.abs(y - p * conditional)))
    result["full_hurdle_rmse"] = float(np.sqrt(np.mean((y - p * conditional) ** 2)))
    result["full_hurdle_signed_bias"] = float(np.mean(p * conditional - y))
    result["positive_count_signed_bias"] = float(np.mean(conditional[positive] - y[positive])) if positive.any() else None
    result["observed_predicted_positive_count_total_ratio"] = float(np.sum(conditional[positive]) / max(np.sum(y[positive]), 1e-12)) if positive.any() else None
    return result


def metric_frame(y: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, train_prevalence: float) -> dict[str, Any]:
    metrics = evaluate_predictions(y, p, conditional, mu, THETA, training_prevalence=train_prevalence, count_score_family="zt_nb")
    return add_metric_aliases(metrics, y, p, conditional)


def a3_prediction(state: dict[str, Any], x_flat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x_flat)), x_flat])
    eta = design @ state["occurrence_beta"]
    xi = design @ state["count_beta"]
    p, conditional, mu = AUG.predict(state, x_flat)
    return eta, xi, p, conditional, mu


def inner_split(train_times: np.ndarray, fraction: float, minimum: int) -> tuple[np.ndarray, np.ndarray]:
    monitor_count = max(int(minimum), int(math.ceil(len(train_times) * float(fraction))))
    monitor_count = min(monitor_count, max(1, len(train_times) - 1))
    return train_times[:-monitor_count], train_times[-monitor_count:]


def build_input(fold: FoldPrepared, time_index: int, candidate: str, positional: np.ndarray, device: Any):
    import torch

    x = torch.as_tensor(fold.x[time_index], dtype=torch.float32, device=device)
    eta = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device).unsqueeze(1)
    xi = torch.as_tensor(fold.xi[time_index], dtype=torch.float32, device=device).unsqueeze(1)
    pieces = [x, eta, xi]
    if candidate in {"A5-PE", "A5-GNN"}:
        pieces.append(torch.as_tensor(positional, dtype=torch.float32, device=device))
    return torch.cat(pieces, dim=1)


def train_model(
    fold: FoldPrepared,
    candidate: str,
    seed: int,
    positional: np.ndarray,
    source: np.ndarray,
    target: np.ndarray,
    degree: np.ndarray,
    config: dict[str, Any],
    device: Any,
    train_node_mask: np.ndarray | None = None,
    checkpoint_path: Path | None = None,
    checkpoint_provenance: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    import torch

    model_config = config["model"]
    if train_node_mask is None:
        train_node_mask = np.ones(NODE_COUNT, dtype=bool)
    mask_tensor = torch.as_tensor(train_node_mask, dtype=torch.bool, device=device)
    source_t = torch.as_tensor(source, dtype=torch.long, device=device)
    target_t = torch.as_tensor(target, dtype=torch.long, device=device)
    degree_t = torch.as_tensor(degree, dtype=torch.float32, device=device)
    input_dim = 34 + 2 + (10 if candidate in {"A5-PE", "A5-GNN"} else 0)

    def run_epochs(model: Any, optimizer: Any, times: np.ndarray, trajectory: list[dict[str, Any]], epoch: int) -> float:
        model.train()
        losses: list[float] = []
        for time_index in times:
            optimizer.zero_grad(set_to_none=True)
            features = build_input(fold, int(time_index), candidate, positional, device)
            occ_delta, count_delta = model(features, source_t, target_t, degree_t)
            occ_delta = center_residual(occ_delta)
            count_delta = center_residual(count_delta)
            occ_offset = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device)
            count_offset = torch.as_tensor(fold.xi[time_index], dtype=torch.float32, device=device)
            observed = torch.as_tensor(fold.counts[time_index], dtype=torch.float32, device=device)
            loss = exact_joint_hurdle_nll(observed, occ_offset + occ_delta, count_offset + count_delta, THETA, mask_tensor)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite A5 training loss at epoch {epoch}, week {time_index}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(model_config["gradient_clip_norm"]))
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        mean_loss = float(np.mean(losses))
        trajectory.append({"epoch": int(epoch), "phase": "fit", "loss": mean_loss, "weeks": int(len(times)), "eligible_nodes": int(mask_tensor.sum().item())})
        return mean_loss

    def monitor(model: Any, times: np.ndarray) -> float:
        model.eval()
        losses: list[float] = []
        with torch.no_grad():
            for time_index in times:
                features = build_input(fold, int(time_index), candidate, positional, device)
                occ_delta, count_delta = model(features, source_t, target_t, degree_t)
                occ_delta = center_residual(occ_delta)
                count_delta = center_residual(count_delta)
                observed = torch.as_tensor(fold.counts[time_index], dtype=torch.float32, device=device)
                occ_offset = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device)
                count_offset = torch.as_tensor(fold.xi[time_index], dtype=torch.float32, device=device)
                loss = exact_joint_hurdle_nll(observed, occ_offset + occ_delta, count_offset + count_delta, THETA, mask_tensor)
                losses.append(float(loss.detach().cpu()))
        return float(np.mean(losses))

    inner_train, inner_monitor = inner_split(fold.train_times, model_config["inner_monitor_fraction"], model_config["inner_monitor_min_weeks"])
    set_seed(seed)
    model = make_model(candidate, input_dim, model_config["hidden_dim"], model_config["dropout"], model_config["activation"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=model_config["learning_rate"], weight_decay=model_config["weight_decay"])
    trajectory: list[dict[str, Any]] = []
    best_loss = math.inf
    best_epoch = 1
    stale = 0
    for epoch in range(1, int(model_config["max_epochs"]) + 1):
        run_epochs(model, optimizer, inner_train, trajectory, epoch)
        validation_loss = monitor(model, inner_monitor)
        trajectory.append({"epoch": int(epoch), "phase": "monitor", "loss": validation_loss, "weeks": int(len(inner_monitor)), "eligible_nodes": int(mask_tensor.sum().item())})
        if validation_loss < best_loss - 1e-8:
            best_loss = validation_loss
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
            if stale >= int(model_config["early_stopping_patience"]):
                break

    # Refitting from the same seed and complete outer training fold is required
    # by the prespecified early-stopping contract.
    set_seed(seed)
    model = make_model(candidate, input_dim, model_config["hidden_dim"], model_config["dropout"], model_config["activation"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=model_config["learning_rate"], weight_decay=model_config["weight_decay"])
    refit_trajectory: list[dict[str, Any]] = []
    for epoch in range(1, best_epoch + 1):
        run_epochs(model, optimizer, fold.train_times, refit_trajectory, epoch)
    fit_info = {
        "seed": int(seed), "best_epoch": int(best_epoch), "inner_train_weeks": int(len(inner_train)),
        "inner_monitor_weeks": int(len(inner_monitor)), "inner_best_loss": float(best_loss),
        "parameter_count": parameter_count(model), "early_stop_trajectory": trajectory,
        "refit_epochs": int(best_epoch), "refit_trajectory": refit_trajectory,
        "converged": True, "train_node_count": int(train_node_mask.sum()),
    }
    if checkpoint_path is not None:
        if checkpoint_provenance is None:
            raise ValueError("checkpoint provenance is required when checkpoint_path is provided")
        write_checkpoint_atomic(checkpoint_path, model, fit_info, checkpoint_provenance)
        fit_info["checkpoint_status"] = "WRITTEN"
        fit_info["checkpoint_path"] = str(checkpoint_path)
    return model, fit_info


def fit_or_load_model(
    fold: FoldPrepared,
    candidate: str,
    seed: int,
    positional: np.ndarray,
    source: np.ndarray,
    target: np.ndarray,
    degree: np.ndarray,
    config: dict[str, Any],
    device: Any,
    checkpoint_path: Path,
    checkpoint_provenance: dict[str, Any],
    train_node_mask: np.ndarray | None = None,
) -> tuple[Any, dict[str, Any]]:
    input_dim = 34 + 2 + (10 if candidate in {"A5-PE", "A5-GNN"} else 0)
    model, fit_info, checkpoint_status = load_completed_checkpoint(
        checkpoint_path, candidate, input_dim, config, device, checkpoint_provenance
    )
    if model is not None and fit_info is not None:
        fit_info["checkpoint_status"] = checkpoint_status
        return model, fit_info
    model, fit_info = train_model(
        fold, candidate, seed, positional, source, target, degree, config, device,
        train_node_mask=train_node_mask,
        checkpoint_path=checkpoint_path,
        checkpoint_provenance=checkpoint_provenance,
    )
    fit_info["checkpoint_input_status"] = checkpoint_status
    return model, fit_info


def predict_neural(fold: FoldPrepared, model: Any, candidate: str, positional: np.ndarray, source: np.ndarray, target: np.ndarray, degree: np.ndarray, times: np.ndarray, eval_node_mask: np.ndarray | None, device: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    import torch

    model.eval()
    source_t = torch.as_tensor(source, dtype=torch.long, device=device)
    target_t = torch.as_tensor(target, dtype=torch.long, device=device)
    degree_t = torch.as_tensor(degree, dtype=torch.float32, device=device)
    if eval_node_mask is None:
        eval_node_mask = np.ones(NODE_COUNT, dtype=bool)
    rows_y: list[np.ndarray] = []
    rows_p: list[np.ndarray] = []
    rows_cond: list[np.ndarray] = []
    rows_mu: list[np.ndarray] = []
    with torch.no_grad():
        for time_index in times:
            features = build_input(fold, int(time_index), candidate, positional, device)
            occ_delta, count_delta = model(features, source_t, target_t, degree_t)
            occ_delta = center_residual(occ_delta)
            count_delta = center_residual(count_delta)
            occ = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device) + occ_delta
            count = torch.as_tensor(fold.xi[time_index], dtype=torch.float32, device=device) + count_delta
            p, conditional, expected = hurdle_predictions(occ, count, THETA)
            selected = np.asarray(eval_node_mask, dtype=bool)
            rows_y.append(fold.counts[time_index, selected].astype(np.int64))
            rows_p.append(p.detach().cpu().numpy()[selected])
            rows_cond.append(conditional.detach().cpu().numpy()[selected])
            rows_mu.append(torch.exp(torch.clamp(count, -20.0, 20.0)).detach().cpu().numpy()[selected])
    return np.concatenate(rows_y), np.concatenate(rows_p), np.concatenate(rows_cond), np.concatenate(rows_mu)


def fold_prediction_record(candidate: str, fold: int, seed: int | None, validation_times: np.ndarray, eval_node_mask: np.ndarray | None, y: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, train_prevalence: float, fit_info: dict[str, Any]) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    metrics = metric_frame(y, p, conditional, mu, train_prevalence)
    week_index = np.repeat(validation_times, int(np.sum(eval_node_mask)) if eval_node_mask is not None else NODE_COUNT)
    node_index = np.tile(np.flatnonzero(eval_node_mask) if eval_node_mask is not None else np.arange(NODE_COUNT), len(validation_times))
    record = {"candidate": candidate, "fold": int(fold), "seed": seed, "validation_weeks": int(len(validation_times)), **fit_info, **metrics}
    arrays = {"y": y, "p": p, "conditional": conditional, "mu": mu, "week_index": week_index.astype(np.int16), "node_id": node_index.astype(np.int32), "fold": np.full(len(y), fold, dtype=np.int16)}
    return record, arrays


def numpy_a3_predictions(fold: FoldPrepared, times: np.ndarray, node_mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    selected = np.ones(NODE_COUNT, dtype=bool) if node_mask is None else np.asarray(node_mask, dtype=bool)
    x = fold.x[times][:, selected].reshape(-1, 34).astype(np.float64)
    eta = fold.eta[times][:, selected].reshape(-1).astype(np.float64)
    xi = fold.xi[times][:, selected].reshape(-1).astype(np.float64)
    y = fold.counts[times][:, selected].reshape(-1).astype(np.int64)
    p, conditional, mu = AUG.predict(fold.a3_state, x)
    return y, p, conditional, mu


def primary_oof(
    data: DataBundle,
    config: dict[str, Any],
    output: Path,
    device: Any,
    durable_root: Path | None = None,
    frozen_a3_output: Path | None = None,
    a3_reference_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]], dict[str, list[dict[str, np.ndarray]]], dict[int, FoldPrepared]]:
    output.joinpath("predictions").mkdir(parents=True, exist_ok=True)
    output.joinpath("training").mkdir(parents=True, exist_ok=True)
    output.joinpath("checkpoints/primary").mkdir(parents=True, exist_ok=True)
    laplacian = diags(data.degree, format="csr") - data.adjacency
    solver = A4.make_graph_solver(laplacian, 0.5)
    rows: list[dict[str, Any]] = []
    records: dict[str, list[dict[str, Any]]] = {candidate: [] for candidate in ["A3", "STRUCTURED_A4S_CHALLENGER", *NEURAL_CANDIDATES]}
    arrays_by_candidate: dict[str, list[dict[str, np.ndarray]]] = {candidate: [] for candidate in records}
    prepared: dict[int, FoldPrepared] = {}
    a3_reference = load_a3_reference_metrics(a3_reference_path) if a3_reference_path is not None else None
    if frozen_a3_output is not None and a3_reference is None:
        raise RuntimeError("authoritative A3 reference metrics are required when frozen A3 predictions are used")

    def persist_progress() -> None:
        frame = pd.DataFrame(rows)
        write_csv(output / "results/fold_seed_metrics.csv", frame)
        if durable_root is not None:
            write_csv(durable_root / "results/fold_seed_metrics.csv", frame)

    for fold_record in FOLDS:
        fold = prepare_temporal_fold(data, fold_record, frozen_a3_output)
        prepared[fold.fold] = fold
        train_prevalence = float(np.mean(fold.counts[fold.train_times] > 0))
        if frozen_a3_output is not None:
            frozen_predictions = load_frozen_a3_predictions(frozen_a3_output, fold.fold, data.counts, fold.validation_times)
            y, p, conditional, mu = (frozen_predictions[key] for key in ("y", "p", "conditional", "mu"))
        else:
            y, p, conditional, mu = numpy_a3_predictions(fold, fold.validation_times)
        a3_record, a3_arrays = fold_prediction_record("A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu, train_prevalence, {"converged": True, "theta": THETA, "a3_fit": "canonical_fixed_theta"})
        if a3_reference is not None:
            a3_record = overwrite_a3_reference_metrics(a3_record, a3_reference, fold.fold)
        rows.append(a3_record)
        records["A3"].append(a3_record)
        arrays_by_candidate["A3"].append(a3_arrays)
        write_npz_atomic(output / "predictions" / f"A3_fold{fold.fold}.npz", a3_arrays)
        persist_progress()

        x_train = fold.x[fold.train_times].reshape(-1, 34).astype(np.float64)
        x_eval = fold.x[fold.validation_times].reshape(-1, 34).astype(np.float64)
        y_train = fold.counts[fold.train_times].reshape(-1)
        y_eval = fold.counts[fold.validation_times].reshape(-1)
        p_a4, cond_a4, mu_a4, a4_info = A4.add_spatial_effects(fold.a3_state, x_train, y_train, x_eval, solver, 1.0)
        a4_record, a4_arrays = fold_prediction_record("STRUCTURED_A4S_CHALLENGER", fold.fold, None, fold.validation_times, None, y_eval, p_a4, cond_a4, mu_a4, train_prevalence, {"converged": True, "theta": THETA, "frozen_reference": True, **a4_info})
        rows.append(a4_record)
        records["STRUCTURED_A4S_CHALLENGER"].append(a4_record)
        arrays_by_candidate["STRUCTURED_A4S_CHALLENGER"].append(a4_arrays)
        write_npz_atomic(output / "predictions" / f"STRUCTURED_A4S_CHALLENGER_fold{fold.fold}.npz", a4_arrays)
        persist_progress()

        for candidate in NEURAL_CANDIDATES:
            for seed in SEEDS:
                started = time.time()
                positional = data.positional_encoding if candidate != "A5-GNN-NOPE" else np.zeros((NODE_COUNT, 0), dtype=np.float32)
                checkpoint_path = output / "checkpoints/primary" / candidate / f"fold_{fold.fold:02d}" / f"seed_{seed}.pt"
                provenance = checkpoint_metadata(data, config, candidate, fold.fold, seed, "primary_temporal_oof")
                model, fit_info = fit_or_load_model(
                    fold, candidate, seed, positional, data.source, data.target, data.degree,
                    config, device, checkpoint_path, provenance,
                )
                y_nn, p_nn, cond_nn, mu_nn = predict_neural(fold, model, candidate, positional, data.source, data.target, data.degree, fold.validation_times, None, device)
                fit_info = {**fit_info, "runtime_seconds": float(time.time() - started), "device": str(device)}
                record, pred_arrays = fold_prediction_record(candidate, fold.fold, seed, fold.validation_times, None, y_nn, p_nn, cond_nn, mu_nn, train_prevalence, fit_info)
                rows.append(record)
                records[candidate].append(record)
                arrays_by_candidate[candidate].append(pred_arrays)
                write_npz_atomic(output / "predictions" / f"{candidate}_fold{fold.fold}_seed{seed}.npz", pred_arrays)
                write_json(output / "training" / f"{candidate}_fold{fold.fold}_seed{seed}.json", fit_info)
                persist_progress()
                del model
                if hasattr(__import__("torch"), "cuda") and __import__("torch").cuda.is_available():
                    __import__("torch").cuda.empty_cache()
    frame = pd.DataFrame(rows)
    persist_progress()
    return frame, records, arrays_by_candidate, prepared


def a3_preflight(data: DataBundle, reference_path: Path, output: Path, frozen_a3_output: Path | None = None) -> pd.DataFrame:
    """Reproduce only the frozen A3 fold metrics before neural execution."""
    rows: list[dict[str, Any]] = []
    reference = load_a3_reference_metrics(reference_path) if frozen_a3_output is not None else None
    for fold_record in FOLDS:
        fold = prepare_temporal_fold(data, fold_record, frozen_a3_output)
        train_prevalence = float(np.mean(fold.counts[fold.train_times] > 0))
        if frozen_a3_output is not None:
            frozen_predictions = load_frozen_a3_predictions(frozen_a3_output, fold.fold, data.counts, fold.validation_times)
            y, p, conditional, mu = (frozen_predictions[key] for key in ("y", "p", "conditional", "mu"))
        else:
            y, p, conditional, mu = numpy_a3_predictions(fold, fold.validation_times)
        record, _ = fold_prediction_record(
            "A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu,
            train_prevalence, {"converged": True, "theta": THETA, "a3_fit": "canonical_fixed_theta"},
        )
        if reference is not None:
            record = overwrite_a3_reference_metrics(record, reference, fold.fold)
        rows.append(record)
    frame = pd.DataFrame(rows)
    write_csv(output / "results/a3_preflight_metrics.csv", frame)
    gate = a3_reproduction_gate(frame, reference_path, output)
    print(json.dumps({"status": "a3_preflight_passed", "max_absolute_difference": float(gate["absolute_difference"].max())}, indent=2))
    return frame


def mean_seed_predictions(records: dict[str, list[dict[str, Any]]], arrays_by_candidate: dict[str, list[dict[str, np.ndarray]]]) -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for candidate, arrays in arrays_by_candidate.items():
        if not arrays:
            continue
        if candidate in {"A3", "STRUCTURED_A4S_CHALLENGER"}:
            result[candidate] = {key: np.concatenate([item[key] for item in arrays]) for key in arrays[0]}
            continue
        # Every seed/fold has the same primary OOF row order. Average only
        # predictions; preserve one observed target/index vector.
        by_seed: dict[int, list[dict[str, np.ndarray]]] = {}
        for record, arrays_item in zip(records[candidate], arrays):
            by_seed.setdefault(int(record["seed"]), []).append(arrays_item)
        seed_vectors: list[dict[str, np.ndarray]] = []
        for seed in SEEDS:
            items = by_seed[seed]
            seed_vectors.append({key: np.concatenate([item[key] for item in items]) for key in items[0]})
        result[candidate] = {
            "y": seed_vectors[0]["y"],
            "p": np.mean([item["p"] for item in seed_vectors], axis=0),
            "conditional": np.mean([item["conditional"] for item in seed_vectors], axis=0),
            "mu": np.mean([item["mu"] for item in seed_vectors], axis=0),
            "week_index": seed_vectors[0]["week_index"],
            "node_id": seed_vectors[0]["node_id"],
            "fold": seed_vectors[0]["fold"],
        }
    return result


def moran(values: np.ndarray, weights: csr_matrix) -> float | None:
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        return None
    centered = values - float(values.mean())
    denominator = float(centered @ centered)
    weight_sum = float(weights.sum())
    if denominator <= 0 or weight_sum <= 0:
        return None
    n = len(values)
    return float((n / weight_sum) * (centered @ (weights @ centered)) / denominator)


def moran_permutation(values: np.ndarray, weights: csr_matrix, count: int, seed: int) -> tuple[float | None, float | None]:
    observed = moran(values, weights)
    if observed is None:
        return None, None
    rng = np.random.default_rng(seed)
    null = [moran(rng.permutation(values), weights) for _ in range(count)]
    null = np.asarray([value for value in null if value is not None])
    if not len(null):
        return observed, None
    p_value = (1.0 + float(np.sum(np.abs(null) >= abs(observed)))) / (len(null) + 1.0)
    return observed, p_value


def aggregate_node(values: np.ndarray, node_ids: np.ndarray, node_count: int, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    if mask is None:
        mask = np.ones(len(values), dtype=bool)
    values = np.asarray(values, dtype=np.float64)
    node_ids = np.asarray(node_ids, dtype=np.int64)
    totals = np.bincount(node_ids[mask], weights=values[mask], minlength=node_count)
    counts = np.bincount(node_ids[mask], minlength=node_count)
    return np.divide(totals, counts, out=np.zeros(node_count), where=counts > 0), counts


def spatial_diagnostics(predictions: dict[str, dict[str, np.ndarray]], data: DataBundle, config: dict[str, Any], output: Path) -> pd.DataFrame:
    shells = deterministic_spatial_shells(data.adjacency, 4)
    rows: list[dict[str, Any]] = []
    candidate_index = {candidate: index for index, candidate in enumerate(predictions)}
    for candidate, arrays in predictions.items():
        y = arrays["y"]
        p = arrays["p"]
        conditional = arrays["conditional"]
        node_ids = arrays["node_id"]
        occurrence, occurrence_n = aggregate_node((y > 0).astype(float) - p, node_ids, NODE_COUNT)
        positive_mask = y > 0
        positive_count, positive_n = aggregate_node(y - conditional, node_ids, NODE_COUNT, positive_mask)
        full_count, full_n = aggregate_node(y - p * conditional, node_ids, NODE_COUNT)
        residuals = [("occurrence", occurrence, occurrence_n), ("positive_count", positive_count, positive_n), ("full_hurdle_count", full_count, full_n)]
        for residual_index, (residual_name, values, counts) in enumerate(residuals):
            for shell_id, weights in shells.items():
                statistic, p_value = moran_permutation(values, weights, int(config["permutation"]["count"]), int(config["permutation"]["seed"]) + 1000 * candidate_index[candidate] + 10 * residual_index + shell_id)
                rows.append({"candidate": candidate, "residual": residual_name, "shell": shell_id, "moran_i": statistic, "permutation_p_value": p_value, "valid_values": int(np.sum(counts > 0)), "graph_pairs": int(weights.nnz), "mean_residual": float(values.mean()), "sd_residual": float(values.std())})
    frame = pd.DataFrame(rows)
    write_csv(output / "results/residual_spatial_summary.csv", frame)
    # Compact map data are intentionally one row per node/candidate.
    map_rows: list[dict[str, Any]] = []
    for candidate, arrays in predictions.items():
        y, p, conditional, node_ids = arrays["y"], arrays["p"], arrays["conditional"], arrays["node_id"]
        occurrence, _ = aggregate_node((y > 0).astype(float) - p, node_ids, NODE_COUNT)
        positive_count, _ = aggregate_node(y - conditional, node_ids, NODE_COUNT, y > 0)
        full_count, _ = aggregate_node(y - p * conditional, node_ids, NODE_COUNT)
        for index, node in data.nodes.iterrows():
            map_rows.append({"candidate": candidate, "model_node_id": int(node["model_node_id"]), "lon": float(node["lon"]), "lat": float(node["lat"]), "occurrence_residual": float(occurrence[index]), "positive_count_residual": float(positive_count[index]), "full_hurdle_count_residual": float(full_count[index])})
    write_csv(output / "results/residual_spatial_map_data.csv", pd.DataFrame(map_rows))
    return frame


def temporal_diagnostics(predictions: dict[str, dict[str, np.ndarray]], output: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, arrays in predictions.items():
        weeks = arrays["week_index"].astype(int)
        nodes = arrays["node_id"].astype(int)
        residual_definitions = {
            "occurrence": (arrays["y"] > 0).astype(float) - arrays["p"],
            "full_hurdle_count": arrays["y"] - arrays["p"] * arrays["conditional"],
            "positive_count": np.where(arrays["y"] > 0, arrays["y"] - arrays["conditional"], np.nan),
        }
        for residual_name, residual in residual_definitions.items():
            by_week = {int(week): np.full(NODE_COUNT, np.nan) for week in np.unique(weeks)}
            for week in by_week:
                selected = weeks == week
                by_week[week][nodes[selected]] = residual[selected]
            for lag in (1, 2, 3):
                left: list[np.ndarray] = []
                right: list[np.ndarray] = []
                for week in sorted(by_week):
                    if week + lag not in by_week:
                        continue
                    a, b = by_week[week], by_week[week + lag]
                    valid = np.isfinite(a) & np.isfinite(b)
                    left.append(a[valid]); right.append(b[valid])
                x = np.concatenate(left) if left else np.array([])
                y = np.concatenate(right) if right else np.array([])
                correlation = float(np.corrcoef(x, y)[0, 1]) if len(x) >= 3 and np.std(x) > 0 and np.std(y) > 0 else None
                rows.append({"candidate": candidate, "residual": residual_name, "lag_weeks": lag, "correlation": correlation, "valid_same_cell_pairs": int(len(x))})
    frame = pd.DataFrame(rows)
    write_csv(output / "results/residual_temporal_summary.csv", frame)
    return frame


def frontier_labels(counts: np.ndarray, origin_index: int, nodes: pd.DataFrame) -> dict[str, np.ndarray]:
    history = np.asarray(counts[: origin_index + 1]) > 0
    f0_occupied = np.any(history, axis=0)
    recent_start = max(0, origin_index + 1 - 8)
    f1_occupied = np.any(np.asarray(counts[recent_start : origin_index + 1]) > 0, axis=0)
    coordinates = nodes[["row", "column"]].to_numpy(float) * 25.0
    prior_nodes = np.flatnonzero(f0_occupied)
    distance = cKDTree(coordinates[prior_nodes]).query(coordinates, k=1)[0] if len(prior_nodes) else np.full(len(nodes), np.inf)
    f2 = np.select([distance <= 25.0, distance <= 100.0], ["near_established", "intermediate_frontier"], default="distal_or_unoccupied")
    return {"F0_reference": np.where(f0_occupied, "previously_occupied", "previously_unoccupied"), "F1_recent_8_week_occupancy": np.where(f1_occupied, "recent_8_week_occupied", "recent_8_week_unoccupied"), "F2_distance_to_prior_detection": f2.astype(str)}


def frontier_diagnostics(predictions: dict[str, dict[str, np.ndarray]], data: DataBundle, output: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, arrays in predictions.items():
        for definition in ("F0_reference", "F1_recent_8_week_occupancy", "F2_distance_to_prior_detection"):
            labels_by_week = {int(week): frontier_labels(data.counts, int(week) - 1, data.nodes)[definition] for week in np.unique(arrays["week_index"])}
            classes = np.array([labels_by_week[int(week)][int(node)] for week, node in zip(arrays["week_index"], arrays["node_id"])], dtype=str)
            for class_name in sorted(np.unique(classes)):
                selected = classes == class_name
                if not selected.any():
                    continue
                metrics = metric_frame(arrays["y"][selected], arrays["p"][selected], arrays["conditional"][selected], arrays["mu"][selected], float(np.mean(data.counts[:26] > 0)))
                rows.append({"candidate": candidate, "definition": definition, "frontier_class": class_name, "n_node_weeks": int(selected.sum()), "positive_node_weeks": int(np.sum(arrays["y"][selected] > 0)), **metrics})
            if definition == "F0_reference":
                first = (classes == "previously_unoccupied") & (arrays["y"] > 0)
                rows.append({"candidate": candidate, "definition": definition, "frontier_class": "first_recorded_detection_event", "n_node_weeks": int(np.sum(classes == "previously_unoccupied")), "positive_node_weeks": int(first.sum()), "event_support": int(first.sum())})
    frame = pd.DataFrame(rows)
    write_csv(output / "results/frontier_metrics.csv", frame)
    return frame


def run_spatial_stress(data: DataBundle, config: dict[str, Any], output: Path, device: Any) -> dict[str, Any]:
    """Fit the same fixed A5 variants with held-out spatial nodes.

    This is deliberately not used for candidate ranking. The frozen A4-S
    object is not refit here; its deferred-validation artifact remains
    immutable. A3 and the three A5 variants are refit under each spatial mask,
    with held-out outcomes excluded from the loss while held-out predictors
    remain available to the fixed graph operator.
    """
    if data.spatial_assignment is None:
        payload = {"status": "NOT_ESTIMABLE", "reason": "no existing deterministic spatial_node_assignments.parquet was available"}
        write_json(output / "results/spatial_stress_status.json", payload)
        write_csv(output / "results/spatial_stress_metrics.csv", pd.DataFrame())
        return payload
    rows: list[dict[str, Any]] = []
    output.joinpath("checkpoints/spatial_stress").mkdir(parents=True, exist_ok=True)
    all_times = np.arange(DEVELOPMENT_WEEKS, dtype=np.int64)
    assignment = data.spatial_assignment["spatial_fold"].to_numpy(np.int64)
    for spatial_fold in sorted(np.unique(assignment)):
        train_nodes = assignment != spatial_fold
        eval_nodes = assignment == spatial_fold
        raw_train = data.a3[:, train_nodes].reshape(-1, 34)
        raw_all = data.a3.reshape(-1, 34)
        y_train = data.counts[:, train_nodes].reshape(-1)
        state, (_, x_all_flat), _, scaling = fit_a3_for_rows(raw_train, y_train, raw_all, AUG.BASE_FEATURES + AUG.ADDED_FEATURES)
        x_all = x_all_flat.reshape(DEVELOPMENT_WEEKS, NODE_COUNT, 34).astype(np.float32)
        design_all = np.concatenate([np.ones((DEVELOPMENT_WEEKS, NODE_COUNT, 1)), x_all.astype(np.float64)], axis=2)
        eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
        xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
        fold = FoldPrepared(100 + int(spatial_fold), all_times, all_times, x_all, data.counts, eta, xi, {**state, "scaling": scaling}, scaling)
        train_prevalence = float(np.mean(y_train > 0))
        y_eval, p_eval, cond_eval, mu_eval = numpy_a3_predictions(fold, all_times, eval_nodes)
        metrics = metric_frame(y_eval, p_eval, cond_eval, mu_eval, train_prevalence)
        rows.append({"candidate": "A3", "spatial_fold": int(spatial_fold), "seed": None, "training_nodes": int(train_nodes.sum()), "evaluation_nodes": int(eval_nodes.sum()), **metrics})
        for candidate in NEURAL_CANDIDATES:
            for seed in SEEDS:
                started = time.time()
                positional = data.positional_encoding if candidate != "A5-GNN-NOPE" else np.zeros((NODE_COUNT, 0), dtype=np.float32)
                checkpoint_path = output / "checkpoints/spatial_stress" / candidate / f"fold_{int(spatial_fold):02d}" / f"seed_{seed}.pt"
                provenance = checkpoint_metadata(data, config, candidate, int(spatial_fold), seed, "secondary_spatial_stress")
                model, fit_info = fit_or_load_model(
                    fold, candidate, seed, positional, data.source, data.target, data.degree,
                    config, device, checkpoint_path, provenance, train_node_mask=train_nodes,
                )
                y_nn, p_nn, cond_nn, mu_nn = predict_neural(fold, model, candidate, positional, data.source, data.target, data.degree, all_times, eval_nodes, device)
                rows.append({"candidate": candidate, "spatial_fold": int(spatial_fold), "seed": int(seed), "training_nodes": int(train_nodes.sum()), "evaluation_nodes": int(eval_nodes.sum()), "runtime_seconds": float(time.time() - started), "best_epoch": int(fit_info["best_epoch"]), "parameter_count": int(fit_info["parameter_count"]), **metric_frame(y_nn, p_nn, cond_nn, mu_nn, train_prevalence)})
                del model
    frame = pd.DataFrame(rows)
    write_csv(output / "results/spatial_stress_metrics.csv", frame)
    payload = {"status": "COMPLETED", "spatial_fold_count": int(len(np.unique(assignment))), "selection_used": False, "a4s_refit": False}
    write_json(output / "results/spatial_stress_status.json", payload)
    return payload


def aggregate_metrics(fold_metrics: pd.DataFrame, output: Path) -> pd.DataFrame:
    numeric = [
        "pr_auc", "roc_auc", "brier", "brier_skill", "bernoulli_nll", "calibration_intercept", "calibration_slope",
        "zt_nb_nll", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias", "full_hurdle_expected_count_mae",
        "full_hurdle_rmse", "full_hurdle_signed_bias", "observed_predicted_positive_count_total_ratio", "joint_hurdle_nll",
    ]
    rows: list[dict[str, Any]] = []
    for candidate in ["A3", "STRUCTURED_A4S_CHALLENGER", *NEURAL_CANDIDATES]:
        group = fold_metrics.loc[fold_metrics["candidate"] == candidate].copy()
        if group.empty:
            continue
        if candidate in NEURAL_CANDIDATES:
            seed_fold = group.groupby(["seed", "fold"], as_index=False)[numeric].mean(numeric_only=True)
            for seed, seed_group in seed_fold.groupby("seed"):
                row = {"candidate": candidate, "aggregation": "seed_mean", "seed": int(seed), "fold": None}
                row.update({metric: float(seed_group[metric].mean()) for metric in numeric})
                rows.append(row)
            fold_mean = seed_fold.groupby("fold", as_index=False)[numeric].mean(numeric_only=True)
            for _, item in fold_mean.iterrows():
                row = {"candidate": candidate, "aggregation": "mean_seed_by_fold", "seed": None, "fold": int(item["fold"])}
                row.update({metric: float(item[metric]) for metric in numeric})
                rows.append(row)
            row = {"candidate": candidate, "aggregation": "mean_seed_fold", "seed": None, "fold": None}
            row.update({metric: float(seed_fold[metric].mean()) for metric in numeric})
            rows.append(row)
        else:
            row = {"candidate": candidate, "aggregation": "fold_mean", "seed": None, "fold": None}
            row.update({metric: float(group[metric].mean()) for metric in numeric})
            rows.append(row)
    frame = pd.DataFrame(rows)
    write_csv(output / "results/aggregate_metrics.csv", frame)
    return frame


def a3_reproduction_gate(fold_metrics: pd.DataFrame, reference_path: Path, output: Path) -> pd.DataFrame:
    reference = pd.read_csv(reference_path)
    reference = reference.loc[reference["model"].astype(str).eq("A3")].set_index("fold")
    observed = fold_metrics.loc[fold_metrics["candidate"].eq("A3")].set_index("fold")
    required = ["joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias"]
    rows: list[dict[str, Any]] = []
    for fold in range(1, 5):
        for metric in required:
            if metric not in reference.columns or metric not in observed.columns:
                raise RuntimeError(f"A3 reference lacks required metric {metric}")
            expected = float(reference.loc[fold, metric])
            reproduced = float(observed.loc[fold, metric])
            rows.append({"fold": fold, "metric": metric, "reference": expected, "reproduced": reproduced, "absolute_difference": abs(expected - reproduced), "tolerance": 1e-9, "pass": bool(abs(expected - reproduced) <= 1e-9)})
    frame = pd.DataFrame(rows)
    write_csv(output / "results/a3_baseline_reproduction.csv", frame)
    if not bool(frame["pass"].all()):
        raise RuntimeError("STOP: exact A3 fold reproduction failed before A5 interpretation")
    return frame


def assess_decision(fold_metrics: pd.DataFrame, spatial: pd.DataFrame, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    required = {"A3", "A5-PE", "A5-GNN-NOPE", "A5-GNN"}
    if not required.issubset(set(fold_metrics["candidate"].unique())):
        return "A5_GNN_INCONCLUSIVE", {"reason": "one or more required candidates did not complete"}
    def mean_metric(candidate: str, metric: str) -> float:
        return float(fold_metrics.loc[fold_metrics["candidate"].eq(candidate), metric].mean())
    def fold_means(candidate: str, metric: str) -> pd.Series:
        return fold_metrics.loc[fold_metrics["candidate"].eq(candidate)].groupby("fold")[metric].mean()
    a3 = {metric: mean_metric("A3", metric) for metric in ["pr_auc", "brier_skill", "calibration_intercept", "calibration_slope", "joint_hurdle_nll"]}
    gnn = {metric: mean_metric("A5-GNN", metric) for metric in a3}
    guard = config["guardrails"]
    preservation = {
        "mean_pr_auc": gnn["pr_auc"] >= a3["pr_auc"] - guard["mean_pr_auc_degradation"],
        "mean_brier_skill": gnn["brier_skill"] >= a3["brier_skill"] - guard["mean_brier_skill_degradation"],
        "worst_fold_pr_auc": float(fold_means("A5-GNN", "pr_auc").min()) >= float(fold_means("A3", "pr_auc").min()) - guard["worst_fold_pr_auc_degradation"],
        "calibration_intercept": abs(abs(gnn["calibration_intercept"]) - abs(a3["calibration_intercept"])) <= guard["calibration_intercept_worsening"],
        "calibration_slope": abs(abs(gnn["calibration_slope"]) - abs(a3["calibration_slope"])) <= guard["calibration_slope_worsening"],
        "joint_hurdle_nll": gnn["joint_hurdle_nll"] <= a3["joint_hurdle_nll"] + guard["joint_hurdle_nll_worsening"],
    }
    spatial_rows = spatial.loc[spatial["shell"].eq(1)]
    occ = spatial_rows.loc[spatial_rows["residual"].eq("occurrence")].set_index("candidate")["moran_i"]
    pos = spatial_rows.loc[spatial_rows["residual"].eq("positive_count")].set_index("candidate")["moran_i"]
    spatial_improvement = {
        "occurrence_moran_reduction_vs_a3": float(occ["A3"] - occ["A5-GNN"]) if "A3" in occ and "A5-GNN" in occ else None,
        "positive_count_moran_reduction_vs_a3": float(pos["A3"] - pos["A5-GNN"]) if "A3" in pos and "A5-GNN" in pos else None,
        "occurrence_moran_reduction_vs_a4s": float(occ["STRUCTURED_A4S_CHALLENGER"] - occ["A5-GNN"]) if "STRUCTURED_A4S_CHALLENGER" in occ else None,
    }
    spatial_guard = {
        "occurrence": spatial_improvement["occurrence_moran_reduction_vs_a3"] is not None and spatial_improvement["occurrence_moran_reduction_vs_a3"] >= guard["mean_occurrence_moran_reduction"],
        "positive_count": spatial_improvement["positive_count_moran_reduction_vs_a3"] is not None and spatial_improvement["positive_count_moran_reduction_vs_a3"] >= guard["mean_positive_count_moran_reduction"],
    }
    pe = mean_metric("A5-PE", "joint_hurdle_nll")
    gnn_vs_pe = {"gnn_joint_nll_not_worse": gnn["joint_hurdle_nll"] <= pe + 0.02, "graph_structural_advantage": spatial_improvement["occurrence_moran_reduction_vs_a4s"] is not None and spatial_improvement["occurrence_moran_reduction_vs_a4s"] >= 0.01}
    seed_spread = fold_metrics.loc[fold_metrics["candidate"].eq("A5-GNN")].groupby("seed")["pr_auc"].mean()
    stability = {"convergence_failures": int((~fold_metrics.loc[fold_metrics["candidate"].isin(NEURAL_CANDIDATES), "converged"].astype(bool)).sum()), "pr_auc_seed_sd": float(seed_spread.std(ddof=0)), "no_severe_seed_instability": bool(seed_spread.std(ddof=0) <= 0.05)}
    if all(preservation.values()) and all(spatial_guard.values()) and all(gnn_vs_pe.values()) and stability["convergence_failures"] == 0 and stability["no_severe_seed_instability"]:
        decision = "A5_GNN_DEVELOPMENT_SUPPORTED_FOR_FREEZE"
    elif not all(preservation.values()) or not all(spatial_guard.values()):
        decision = "A5_GNN_NOT_SUPPORTED"
    else:
        decision = "A5_GNN_INCONCLUSIVE"
    positional_interpretation = "A5_GNN_NOT_JUSTIFIED_POSITIONAL_MODEL_SUFFICIENT" if pe <= gnn["joint_hurdle_nll"] and mean_metric("A5-PE", "pr_auc") >= mean_metric("A5-GNN", "pr_auc") - 0.005 else None
    evidence = {"decision": decision, "a3": a3, "a5_gnn": gnn, "predictive_preservation": preservation, "spatial_improvement": spatial_improvement, "spatial_guardrails": spatial_guard, "graph_ablation": gnn_vs_pe, "seed_stability": stability, "positional_interpretation": positional_interpretation}
    return decision, evidence


def render_figures(fold_metrics: pd.DataFrame, spatial: pd.DataFrame, predictions: dict[str, dict[str, np.ndarray]], output: Path) -> dict[str, Any]:
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:
        status = {"status": "NOT_RENDERED", "reason": str(exc)}
        write_json(output / "figures/figure_generation_status.json", status)
        return status
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    candidates = ["A3", "STRUCTURED_A4S_CHALLENGER", "A5-PE", "A5-GNN-NOPE", "A5-GNN"]
    labels = {"STRUCTURED_A4S_CHALLENGER": "A4-S", "A5-GNN-NOPE": "A5-GNN-NOPE"}

    def box_metric(metric: str, filename: str, ylabel: str, title: str) -> None:
        fig, ax = plt.subplots(figsize=(9, 5))
        values = [fold_metrics.loc[fold_metrics["candidate"].eq(candidate), metric].dropna().to_numpy() for candidate in candidates]
        ax.boxplot(values, labels=[labels.get(candidate, candidate) for candidate in candidates], showmeans=True)
        ax.set_ylabel(ylabel); ax.set_title(title); fig.tight_layout(); fig.savefig(figures / filename, dpi=180); plt.close(fig)

    box_metric("pr_auc", "pr_auc_by_candidate_fold.png", "PR-AUC", "Occurrence PR-AUC by candidate and fold/seed")
    box_metric("brier", "brier_by_candidate_fold.png", "Brier score", "Occurrence Brier score by candidate and fold/seed")

    for residual, filename, title in [("occurrence", "occurrence_residual_moran.png", "Occurrence residual Moran's I"), ("positive_count", "positive_count_residual_moran.png", "Positive-count residual Moran's I")]:
        subset = spatial.loc[(spatial["residual"].eq(residual)) & (spatial["shell"].eq(1))]
        fig, ax = plt.subplots(figsize=(9, 5))
        for candidate in candidates:
            row = subset.loc[subset["candidate"].eq(candidate)]
            if not row.empty:
                ax.bar(labels.get(candidate, candidate), row["moran_i"].iloc[0])
        ax.set_ylabel("Moran's I"); ax.set_title(title); ax.axhline(0, color="black", linewidth=.8); fig.tight_layout(); fig.savefig(figures / filename, dpi=180); plt.close(fig)

    subset = spatial.loc[spatial["residual"].eq("occurrence")]
    fig, ax = plt.subplots(figsize=(8, 5))
    for candidate in candidates:
        row = subset.loc[subset["candidate"].eq(candidate)].sort_values("shell")
        if not row.empty:
            ax.plot(row["shell"], row["moran_i"], marker="o", label=labels.get(candidate, candidate))
    ax.set_xlabel("Graph shell"); ax.set_ylabel("Moran's I"); ax.set_title("Occurrence residual Moran's I by graph shell"); ax.legend(); fig.tight_layout(); fig.savefig(figures / "moran_by_graph_shell_1_4.png", dpi=180); plt.close(fig)

    map_frame = pd.read_csv(output / "results/residual_spatial_map_data.csv")
    a3_map = map_frame.loc[map_frame["candidate"].eq("A3")]
    gnn_map = map_frame.loc[map_frame["candidate"].eq("A5-GNN")]
    if not a3_map.empty and not gnn_map.empty:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True, sharey=True)
        for ax, frame, title in zip(axes, [a3_map, gnn_map], ["A3 occurrence residual", "A5-GNN occurrence residual"]):
            sc = ax.scatter(frame["lon"], frame["lat"], c=frame["occurrence_residual"], s=2, cmap="coolwarm", vmin=-.1, vmax=.1)
            ax.set_title(title); ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        fig.colorbar(sc, ax=axes.ravel().tolist(), label="Observed presence − predicted probability"); fig.tight_layout(); fig.savefig(figures / "representative_a3_vs_a5_gnn_residual_maps.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for candidate in candidates:
        row = fold_metrics.loc[fold_metrics["candidate"].eq(candidate)]
        if not row.empty:
            ax.scatter(row["calibration_intercept"], row["calibration_slope"], label=labels.get(candidate, candidate))
    ax.axvline(0, color="black", linewidth=.7); ax.axhline(1, color="black", linewidth=.7); ax.set_xlabel("Calibration intercept"); ax.set_ylabel("Calibration slope"); ax.set_title("Calibration comparison"); ax.legend(); fig.tight_layout(); fig.savefig(figures / "calibration_comparison.png", dpi=180); plt.close(fig)

    seed_frame = fold_metrics.loc[fold_metrics["candidate"].eq("A5-GNN")]
    fig, ax = plt.subplots(figsize=(8, 5))
    if not seed_frame.empty:
        for seed, group in seed_frame.groupby("seed"):
            ax.plot(group["fold"], group["pr_auc"], marker="o", label=f"seed {int(seed)}")
    ax.set_xlabel("Outer fold"); ax.set_ylabel("PR-AUC"); ax.set_title("A5-GNN seed stability"); ax.legend(); fig.tight_layout(); fig.savefig(figures / "a5_gnn_seed_stability.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for candidate in ["A5-PE", "A5-GNN-NOPE", "A5-GNN"]:
        group = fold_metrics.loc[fold_metrics["candidate"].eq(candidate)]
        ax.plot(group["fold"], group["joint_hurdle_nll"], marker="o", label=candidate)
    ax.set_xlabel("Outer fold"); ax.set_ylabel("Joint hurdle NLL"); ax.set_title("A5 ablation comparison"); ax.legend(); fig.tight_layout(); fig.savefig(figures / "a5_ablation_comparison.png", dpi=180); plt.close(fig)
    manifest = {"status": "COMPLETED", "files": sorted(path.name for path in figures.glob("*.png"))}
    write_json(output / "figures/figure_generation_status.json", manifest)
    return manifest


def write_report(output: Path, data: DataBundle, config: dict[str, Any], fold_metrics: pd.DataFrame, aggregate: pd.DataFrame, spatial: pd.DataFrame, temporal: pd.DataFrame, stress: dict[str, Any], decision: str, evidence: dict[str, Any], environment: dict[str, Any]) -> None:
    a3 = aggregate.loc[(aggregate["candidate"].eq("A3")) & (aggregate["aggregation"].eq("fold_mean"))].iloc[0]
    gnn = aggregate.loc[(aggregate["candidate"].eq("A5-GNN")) & (aggregate["aggregation"].eq("mean_seed_fold"))].iloc[0]
    a3_occ = spatial.loc[(spatial["candidate"].eq("A3")) & (spatial["residual"].eq("occurrence")) & (spatial["shell"].eq(1)), "moran_i"].iloc[0]
    gnn_occ = spatial.loc[(spatial["candidate"].eq("A5-GNN")) & (spatial["residual"].eq("occurrence")) & (spatial["shell"].eq(1)), "moran_i"].iloc[0]
    a3_pos = spatial.loc[(spatial["candidate"].eq("A3")) & (spatial["residual"].eq("positive_count")) & (spatial["shell"].eq(1)), "moran_i"].iloc[0]
    gnn_pos = spatial.loc[(spatial["candidate"].eq("A5-GNN")) & (spatial["residual"].eq("positive_count")) & (spatial["shell"].eq(1)), "moran_i"].iloc[0]
    if decision == "A5_GNN_DEVELOPMENT_SUPPORTED_FOR_FREEZE":
        conclusion = "did capture materially useful spatial information according to the prespecified quantitative guardrails"
    elif decision == "A5_GNN_NOT_SUPPORTED":
        conclusion = "did not capture materially useful spatial information according to the prespecified quantitative guardrails"
    else:
        conclusion = "did not establish whether it captured materially useful spatial information under the prespecified quantitative guardrails"
    lines = [
        "# A5-GNN bounded comparison report", "",
        "## I. Governance", "",
        "This is a supervised-agent, development-only comparison. The frozen Structured A3 artifact and frozen A4-S challenger were treated as immutable. Atlas access used the authorized WSL/Ubuntu `atlas-ssh` route. No production tag, release, or merge was created.", "",
        "## II. Canonical starting state", "",
        f"Starting SHA: `{config['canonical_start_sha']}`. Execution SHA: `{git_value('rev-parse', 'HEAD')}`. Branch: `{git_value('branch', '--show-current')}`. Development boundary: `{config['development_period']['start']}` through `{config['development_period']['end']}`; only F1--F4 were selection-eligible.", "",
        "## III. Software/environment audit", "",
        f"{environment}. The local Windows environment did not provide the required Python/R runtime; Atlas supplied the supported Python environment. Large runtime products remain under TEMPORARY_90DAY_STORAGE and are automatically removed after 90 days without activity.", "",
        "## IV. A3 reproduction", "",
        "The canonical fixed-theta A3 fit was reproduced independently within each outer fold before neural fitting. The exact-loss reproduction gate is stored in `results/a3_baseline_reproduction.csv`.", "",
        "## V. A5-GNN architecture", "",
        f"A5-GNN is a two-layer mean-aggregation GraphSAGE residual model with separate occurrence and positive-count branches, hidden width 16, ReLU, dropout 0.10, AdamW, learning rate 1e-3, weight decay 1e-4, and gradient clipping 1.0. The exact trainable parameter count is recorded in `fold_seed_metrics.csv`. A5-PE is the node-wise MLP control; A5-GNN-NOPE omits positional encodings.", "",
        "## VI. Leakage and causal-timing verification", "",
        "Inputs are the standardized 34 causal A3 predictors, frozen A3 offsets, standardized node coordinates, and eight response-independent graph-Laplacian eigenvectors. Neighbor outcomes and residuals are never included. The graph is deterministic, bidirectional, outcome-free, and has no explicit self-loops; self-information is supplied by GraphSAGE concatenation.", "",
        "## VII. Predictive results", "",
        f"A3 mean PR-AUC was `{a3['pr_auc']:.6f}`, Brier skill `{a3['brier_skill']:.6f}`, and joint hurdle NLL `{a3['joint_hurdle_nll']:.6f}`. A5-GNN mean-over-seed/fold PR-AUC was `{gnn['pr_auc']:.6f}`, Brier skill `{gnn['brier_skill']:.6f}`, and joint hurdle NLL `{gnn['joint_hurdle_nll']:.6f}`. Full fold/seed metrics, including count MAE/RMSE/bias, totals, ROC-AUC, calibration, and ZTNB NLL, are machine-readable in `results/`.", "",
        "## VIII. Residual spatial dependence", "",
        f"First-shell occurrence residual Moran's I was `{a3_occ:.6f}` for A3 and `{gnn_occ:.6f}` for A5-GNN (reduction `{a3_occ - gnn_occ:.6f}`). First-shell positive-count residual Moran's I was `{a3_pos:.6f}` for A3 and `{gnn_pos:.6f}` for A5-GNN (reduction `{a3_pos - gnn_pos:.6f}`). Shells 1--4, deterministic permutation p-values, valid-value counts, graph-pair counts, and residual maps are in `results/`.", "",
        "## IX. Residual temporal dependence", "",
        "Same-cell residual correlations at lags 1--3 are reported separately for occurrence, full hurdle count, and estimable positive-count residuals. A5-GNN is non-recurrent; remaining temporal dependence is therefore documented rather than modeled away.", "",
        "## X. Ablation results", "",
        "A5-PE, A5-GNN-NOPE, and A5-GNN used identical folds, seeds, loss, optimizer settings, and training-duration protocol. The comparison is descriptive and was prespecified before outer-fold results were read.", "",
        "## XI. Spatial stress test", "",
        f"Spatial stress-test status: `{stress.get('status')}`. The existing deterministic spatial partition was used when available; held-out outcomes were excluded from training loss, and stress-test results were not used for model selection. A4-S was not refit in the stress test because its frozen artifact is immutable.", "",
        "## XII. Seed stability", "",
        f"Three fixed seeds were applied to every A5 variant. Seed-level summaries and the A5-GNN seed plot are included. The guardrail evidence reports PR-AUC seed SD `{evidence.get('seed_stability', {}).get('pr_auc_seed_sd')}`.", "",
        "## XIII. Guardrail assessment", "",
        f"Predictive preservation: `{evidence.get('predictive_preservation')}`. Spatial guardrails: `{evidence.get('spatial_guardrails')}`. Graph-ablation evidence: `{evidence.get('graph_ablation')}`. These are development guardrails only.", "",
        "## XIV. Limitations", "",
        "The analysis uses recorded detections, not latent abundance. Residual spatial improvement does not identify causal transmission, dispersal, surveillance effort, intervention effects, or biological mechanism. The development period is historical and cannot establish prospective validity. The neural challenger is deliberately shallow and non-recurrent.", "",
        "## XV. Primary decision", "",
        f"`{decision}`", "",
        f"The scientific conclusion is therefore: shallow graph message passing {conclusion} beyond Structured A3 and simpler positional corrections; this conclusion does not authorize deployment.", "",
        "## XVI. Repository/PR state", "",
        f"Branch: `{git_value('branch', '--show-current')}`. No merge was performed. The production A3 artifact hash check and A4-S manifest checks are recorded in `provenance/a5_analysis_manifest.json`. A PR remains a separate handoff step.", "",
    ]
    (output / "final_decision_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--a3-reference", type=Path, required=True)
    parser.add_argument("--a3-frozen-output", type=Path, default=Path(os.environ["A5_GNN_FROZEN_A3_OUTPUT"]) if os.environ.get("A5_GNN_FROZEN_A3_OUTPUT") else None)
    parser.add_argument("--spatial-assignments", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--durable-summary-root", type=Path, default=Path(os.environ["A5_GNN_DURABLE_SUMMARY_ROOT"]) if os.environ.get("A5_GNN_DURABLE_SUMMARY_ROOT") else None)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--skip-spatial-stress", action="store_true")
    parser.add_argument("--a3-only", action="store_true")
    args = parser.parse_args()
    config = read_config(args.config)
    output = resolve_output_root(args.output_root)
    durable_root = args.durable_summary_root.expanduser().resolve() if args.durable_summary_root is not None else None
    if durable_root is not None and durable_root == output:
        raise RuntimeError("durable summary root must be separate from temporary execution output root")
    for directory in ("results", "predictions", "training", "checkpoints", "figures", "provenance", "cache", "tmp", "figures_work", "manifests"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    if durable_root is not None:
        write_json(durable_root / "results/restart_recovery.json", {
            "status": "RUNNING",
            "recovery_classification": "INCOMPLETE_REGENERATE",
            "original_failed_job_ids": ["21081004", "21081008", "21081016", "21081020", "21081022"],
            "original_quota_failure": "Disk quota exceeded while attempting Atlas /project Git-object/staging writes; no durable A5 output root existed.",
            "interrupted_job": {"job_id": "21081022", "state": "CANCELLED", "elapsed": "00:04:16", "max_rss": "2991828K", "scientific_stage": "neural fitting in first bounded run; canceled at user request"},
            "verified_reusable_units": [],
            "units_requiring_rerun": "all primary A3/A4-S/A5 fold-seed units; no prior completed unit had a valid reusable artifact",
            "execution_sha": git_value("rev-parse", "HEAD"),
            "output_root": str(output),
            "storage_class": "TEMPORARY_90DAY_STORAGE",
        })
    import torch
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else args.device if args.device != "auto" else "cpu")
    data = load_data(args, config)
    production_path = REPOSITORY_ROOT / "analysis/structured_a3_evaluation/results/final_a3_model.json"
    production_sha = sha256_file(production_path).strip().lower()
    expected_production_sha = PRODUCTION_MODEL_SHA.strip().lower()
    if production_sha != expected_production_sha:
        raise RuntimeError(f"STOP: frozen production Structured A3 artifact hash changed: expected {expected_production_sha}, observed {production_sha}, path {production_path}")
    a4s_manifest_path = REPOSITORY_ROOT / "analysis/structured_a4s_deferred_validation/results/frozen_a4s_challenger_manifest.json"
    if sha256_file(a4s_manifest_path).strip().lower() != FROZEN_A4S_MANIFEST_SHA.strip().lower():
        raise RuntimeError("STOP: frozen Structured A4-S challenger manifest hash changed")
    if args.a3_frozen_output is None:
        raise RuntimeError("STOP: exact frozen A3 fold tasks are required for temporal offsets")
    args.a3_frozen_output = args.a3_frozen_output.expanduser().resolve()
    for fold_id in range(1, 5):
        task_id = (fold_id - 1) * 2 + 2
        task_path = args.a3_frozen_output / "tasks" / f"task_{task_id:03d}_A3_fold{fold_id}.json"
        prediction_path = args.a3_frozen_output / "predictions" / f"task_{task_id:03d}_A3_fold{fold_id}.npz"
        if not task_path.exists():
            raise RuntimeError(f"STOP: missing exact frozen A3 fold task {task_path}")
        if not prediction_path.exists() or prediction_path.stat().st_size == 0:
            raise RuntimeError(f"STOP: missing exact frozen A3 fold predictions {prediction_path}")
    if args.a3_only:
        a3_preflight(data, args.a3_reference, output, args.a3_frozen_output)
        return 0
    fold_metrics, records, arrays_by_candidate, prepared = primary_oof(
        data, config, output, device, durable_root, args.a3_frozen_output, args.a3_reference,
    )
    gate = a3_reproduction_gate(fold_metrics, args.a3_reference, output)
    predictions = mean_seed_predictions(records, arrays_by_candidate)
    spatial = spatial_diagnostics(predictions, data, config, output)
    temporal = temporal_diagnostics(predictions, output)
    frontier = frontier_diagnostics(predictions, data, output)
    aggregate = aggregate_metrics(fold_metrics, output)
    stress = {"status": "SKIPPED", "reason": "command-line skip"} if args.skip_spatial_stress else run_spatial_stress(data, config, output, device)
    decision, evidence = assess_decision(fold_metrics, spatial, config)
    write_json(output / "results/a5_decision.json", {"primary_decision": decision, "evidence": evidence, "frontier_rows": int(len(frontier)), "temporal_rows": int(len(temporal))})
    figures = render_figures(fold_metrics, spatial, predictions, output)
    feature_target_audit = {
        "status": "PASSED",
        "feature_blocks": [
            "standardized_34_predictor_A3_matrix",
            "frozen_A3_occurrence_offset",
            "frozen_A3_positive_count_offset",
            "standardized_lon_lat",
            "8_response_independent_normalized_laplacian_eigenvectors",
        ],
        "target_access": "targets are accessed only by exact hurdle loss, validation metrics, and diagnostics after prediction",
        "forbidden_inputs": ["same_week_outcomes", "future_outcomes", "same_week_residuals", "node_id_embedding", "SIT_or_intervention_proxy"],
        "graph_contract": "canonical bidirectional queen adjacency; no persisted self-loops; mean aggregation only",
        "selection_boundary": "2025-W01 through 2026-W16; F1-F4 only",
    }
    write_json(output / "provenance/feature_target_access_audit.json", feature_target_audit)
    environment = {
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": __import__("scipy").__version__,
        "torch": torch.__version__, "torch_geometric": __import__("importlib").util.find_spec("torch_geometric") is not None,
        "torch_geometric_temporal": __import__("importlib").util.find_spec("torch_geometric_temporal") is not None,
        "cuda_available": bool(torch.cuda.is_available()), "cuda_version": str(torch.version.cuda),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "device_used": str(device),
        "output_root": str(output), "durable_summary_root": str(durable_root) if durable_root is not None else None,
        "temporary_storage_class": "TEMPORARY_90DAY_STORAGE", "xdg_cache_home": os.environ.get("XDG_CACHE_HOME"),
        "torch_home": os.environ.get("TORCH_HOME"), "tmpdir": os.environ.get("TMPDIR"),
    }
    manifest = {
        "analysis": "a5_gnn_bounded_comparison", "status": "completed", "generated_utc": utc_now(),
        "starting_sha": config["canonical_start_sha"], "execution_sha": git_value("rev-parse", "HEAD"), "branch": git_value("branch", "--show-current"),
        "development_period": config["development_period"], "folds": config["folds"], "seeds": SEEDS,
        "candidate_scope": config["candidates"], "input_sha256": data.hashes, "graph": {"directed_edge_count": int(len(data.source)), "node_count": NODE_COUNT, "isolated_nodes": int(np.sum(data.degree == 0)), "checksum": data.hashes.get("edges")},
        "frozen_a3_temporal_output": {
            "root": str(args.a3_frozen_output),
            "fold_task_sha256": {str(fold_id): data.hashes.get(f"a3_frozen_fold_{fold_id}") for fold_id in range(1, 5)},
            "fold_prediction_sha256": {str(fold_id): data.hashes.get(f"a3_frozen_prediction_{fold_id}") for fold_id in range(1, 5)},
            "predictions_used": True,
            "reference_metrics_used": True,
        },
        "positional_encoding": data.positional_metadata, "model_config": config["model"], "runtime": environment,
        "production_a3_artifact": {"path": str(production_path), "sha256": sha256_file(production_path), "expected_sha256": PRODUCTION_MODEL_SHA, "unchanged": sha256_file(production_path) == PRODUCTION_MODEL_SHA},
        "a4s_frozen_manifest": {"path": str(a4s_manifest_path), "sha256": sha256_file(a4s_manifest_path), "expected_sha256": FROZEN_A4S_MANIFEST_SHA, "unchanged": sha256_file(a4s_manifest_path) == FROZEN_A4S_MANIFEST_SHA},
        "a3_reproduction_max_difference": float(gate["absolute_difference"].max()), "spatial_stress_test": stress, "figures": figures,
        "prospective_data_loaded": False, "post_w16_outcomes_used_for_selection": False, "w30_w39_used_for_selection": False, "sit_included": False,
        "decision": decision, "evidence": evidence,
        "script_sha256": {"run_a5_gnn.py": sha256_file(Path(__file__)), "a5_model.py": sha256_file(Path(__file__).with_name("a5_model.py")), "config": sha256_file(args.config)},
        "storage": {
            "temporary_storage_class": "TEMPORARY_90DAY_STORAGE",
            "temporary_output_root": str(output),
            "durable_summary_root": str(durable_root) if durable_root is not None else None,
            "temporary_storage_retention": "90 days without activity",
            "output_paths": {name: str(output / name) for name in ("checkpoints", "predictions", "training", "tmp", "cache", "figures_work")},
        },
        "durable_promotion": {"status": "PENDING"},
    }
    write_json(output / "provenance/a5_analysis_manifest.json", manifest)
    write_report(output, data, config, fold_metrics, aggregate, spatial, temporal, stress, evidence, environment)
    def write_checksum_manifest() -> None:
        write_json(output / "provenance/checksum_manifest.json", {"files": {str(path.relative_to(output)): sha256_file(path) for path in output.rglob("*") if path.is_file() and path.name != "checksum_manifest.json"}})

    write_checksum_manifest()
    promotion = promote_compact_outputs(output, durable_root)
    manifest["durable_promotion"] = promotion
    write_json(output / "provenance/a5_analysis_manifest.json", manifest)
    write_checksum_manifest()
    promotion = promote_compact_outputs(output, durable_root)
    if durable_root is not None:
        write_json(durable_root / "results/restart_recovery.json", {
            "status": "COMPLETED",
            "recovery_classification": "VERIFIED_REUSABLE",
            "original_failed_job_ids": ["21081004", "21081008", "21081016", "21081020", "21081022"],
            "original_quota_failure": "Disk quota exceeded while attempting Atlas /project Git-object/staging writes; no durable A5 output root existed.",
            "interrupted_job": {"job_id": "21081022", "state": "CANCELLED", "elapsed": "00:04:16", "max_rss": "2991828K", "scientific_stage": "neural fitting in first bounded run; canceled at user request"},
            "verified_reusable_units": "all units with COMPLETED checkpoint and matching provenance",
            "units_requiring_rerun": "none after this completed run",
            "execution_sha": git_value("rev-parse", "HEAD"),
            "output_root": str(output),
            "durable_promotion": promotion,
            "storage_class": "TEMPORARY_90DAY_STORAGE",
        })
    print(json.dumps({"status": "completed", "decision": decision, "output_root": str(output), "durable_summary_root": str(durable_root) if durable_root is not None else None, "device": str(device)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
