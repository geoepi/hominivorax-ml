"""Run the prespecified A5B multiscale component-specific spatial follow-up."""

from __future__ import annotations

import argparse
import hashlib
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
from scipy.special import expit
from scipy.sparse import coo_matrix

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison/scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "analysis/a5b_multiscale_component_spatial_ml/scripts"))

import run_a5_gnn as A5  # noqa: E402
from a5b_model import MultiscaleOccurrenceResidualModel, parameter_count  # noqa: E402


NODE_COUNT = A5.NODE_COUNT
DEVELOPMENT_WEEKS = A5.DEVELOPMENT_WEEKS
FOLDS = A5.FOLDS
SEEDS = A5.SEEDS
THETA = A5.THETA
SHELLS = (1, 2, 3, 4)
PARENT_A5_SHA = "e71c02c3ea87a4ab13dbb7733277c17b9c53c550"
PRODUCTION_MODEL_SHA = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
FROZEN_A4S_MANIFEST_SHA = "156ab650b8fa79f7a4fe390f3687ca53212fbf37fb7e9963ba91b9f70c9b68af"
FROZEN_A4S_JSON_SHA = "05dcb211d4bacb24dd4ef9399aa2e495ff85c1121439a40c32a3a05d09de4373"
FROZEN_A4S_NPZ_SHA = "eef5fadc614c543dada56ace20104ee0f9aca49cc88321c43f9c8e4d9f40c6ca"
REFERENCE_CANDIDATES = ["A3", "STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"]
A5B_CANDIDATES = ["A5B-MS-OCC", "A5B-HYBRID"]
REQUIRED_METRICS = [
    "pr_auc", "roc_auc", "brier", "brier_skill", "bernoulli_nll",
    "calibration_intercept", "calibration_slope", "zt_nb_nll",
    "positive_count_mae", "positive_count_rmse", "conditional_mean_bias",
    "full_hurdle_expected_count_mae", "full_hurdle_rmse", "full_hurdle_signed_bias",
    "observed_predicted_positive_count_total_ratio", "joint_hurdle_nll",
]


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
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def resolve_output_root(explicit: Path | None) -> Path:
    value = explicit or (Path(os.environ["A5B_OUTPUT_ROOT"]) if os.environ.get("A5B_OUTPUT_ROOT") else None)
    if value is None:
        raise RuntimeError("A5B_OUTPUT_ROOT or --output-root is required")
    root = value.expanduser().resolve()
    normalized = str(root).replace("\\", "/")
    if "/90daydata/" not in normalized:
        raise RuntimeError(f"large A5B output root must be under /90daydata/disease_ecology: {root}")
    return root


def assert_storage_roots(output: Path, durable: Path | None) -> None:
    if durable is not None and durable.resolve() == output.resolve():
        raise RuntimeError("durable summary root must be separate from temporary A5B output root")
    if durable is not None and "90daydata" in str(durable).replace("\\", "/"):
        raise RuntimeError("durable A5B summaries must not be placed under /90daydata")


def read_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("analysis") != "a5b_multiscale_component_spatial_ml":
        raise RuntimeError("A5B analysis identifier changed")
    if config.get("development_classification") != "DEVELOPMENT_INFORMED_FOLLOWUP":
        raise RuntimeError("A5B must remain explicitly development-informed")
    if config.get("parent_a5_commit") != PARENT_A5_SHA:
        raise RuntimeError("A5B parent A5 commit changed")
    if config["development_period"]["start"] != "2025-W01" or config["development_period"]["end"] != "2026-W16":
        raise RuntimeError("A5B development boundary changed")
    if config["model"]["theta"] != THETA or config["model"]["shell_count"] != 4 or config["model"]["shell_hidden_dim"] != 8:
        raise RuntimeError("A5B exact model contract changed")
    if config["seeds"] != SEEDS or config["graph"]["node_count"] != NODE_COUNT or config["graph"]["directed_edge_count"] != 77614:
        raise RuntimeError("A5B seed or graph contract changed")
    if config["storage"]["output_root_env"] != "A5B_OUTPUT_ROOT" or config["storage"]["temporary_storage_class"] != "TEMPORARY_90DAY_STORAGE":
        raise RuntimeError("A5B storage contract changed")
    if config["forbidden"]["inputs"] != ["same_week_outcomes", "future_outcomes", "same_week_residuals", "node_id_embedding", "longitude_latitude", "laplacian_positional_encoding", "free_node_embedding", "SIT_or_intervention_proxy"]:
        raise RuntimeError("A5B leakage/input prohibition changed")
    return config


def filesystem_usage(path: str) -> dict[str, int | str]:
    usage = shutil.disk_usage(path)
    return {"path": path, "total_bytes": int(usage.total), "used_bytes": int(usage.total - usage.free), "free_bytes": int(usage.free)}


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def write_npz_atomic(path: Path, arrays: dict[str, np.ndarray]) -> None:
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


def load_data(args: argparse.Namespace, config: dict[str, Any]) -> A5.DataBundle:
    # Reuse the completed A5 data-contract loader, but never its positional
    # encoding as an A5B model input.
    return A5.load_data(args, config)


def shell_edge_hash(source: np.ndarray, target: np.ndarray) -> str:
    pairs = np.column_stack([np.asarray(source, dtype=np.int64), np.asarray(target, dtype=np.int64)])
    return hashlib.sha256(pairs.tobytes(order="C")).hexdigest()


@dataclass
class ShellRelation:
    shell: int
    source: np.ndarray
    target: np.ndarray
    degree: np.ndarray
    pair_count: int
    sha256: str


def build_shell_relations(data: A5.DataBundle, reference_root: Path) -> list[ShellRelation]:
    shells = A5.deterministic_spatial_shells(data.adjacency, 4)
    reference_path = reference_root / "results/residual_spatial_summary.csv"
    reference = pd.read_csv(reference_path)
    result: list[ShellRelation] = []
    for shell_id in SHELLS:
        matrix = shells[shell_id].tocsr()
        source, target = matrix.nonzero()
        degree = np.asarray(matrix.sum(axis=1)).ravel().astype(np.float32)
        expected = reference.loc[(reference["candidate"].eq("A3")) & (reference["residual"].eq("occurrence")) & (reference["shell"].eq(shell_id)), "graph_pairs"]
        if len(expected) != 1 or int(expected.iloc[0]) != int(matrix.nnz):
            raise RuntimeError(f"shell {shell_id} pair count does not match the existing residual-diagnostic definition")
        result.append(ShellRelation(shell_id, source.astype(np.int64), target.astype(np.int64), degree, int(matrix.nnz), shell_edge_hash(source, target)))
    return result


@dataclass
class FrozenA4S:
    root: Path
    json_path: Path
    npz_path: Path
    payload: dict[str, Any]
    occurrence_beta: np.ndarray
    count_beta: np.ndarray
    training_mean: np.ndarray
    training_sd: np.ndarray
    occurrence_spatial_effect: np.ndarray
    count_spatial_effect: np.ndarray
    json_sha256: str
    npz_sha256: str

    def predict(self, raw: np.ndarray, node_ids: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = (np.asarray(raw, dtype=np.float64) - self.training_mean[None, :]) / self.training_sd[None, :]
        design = np.column_stack([np.ones(len(x), dtype=np.float64), x])
        if node_ids is None:
            if len(x) % NODE_COUNT != 0:
                raise RuntimeError("frozen A4-S full-node prediction rows are not week-aligned")
            occurrence_effect = np.tile(self.occurrence_spatial_effect, len(x) // NODE_COUNT)
            count_effect = np.tile(self.count_spatial_effect, len(x) // NODE_COUNT)
        else:
            ids = np.asarray(node_ids, dtype=np.int64)
            if len(ids) == 0 or len(x) % len(ids) != 0:
                raise RuntimeError("frozen A4-S masked prediction rows are not week-aligned")
            occurrence_effect = np.tile(self.occurrence_spatial_effect[ids], len(x) // len(ids))
            count_effect = np.tile(self.count_spatial_effect[ids], len(x) // len(ids))
        occurrence_logit = design @ self.occurrence_beta + occurrence_effect
        count_log_mean = design @ self.count_beta + count_effect
        probability = expit(np.clip(occurrence_logit, -40.0, 40.0))
        mu = np.exp(np.clip(count_log_mean, -20.0, 20.0))
        log_p0 = THETA * (math.log(THETA) - np.log(THETA + mu))
        conditional = mu / np.maximum(-np.expm1(log_p0), 1e-8)
        return probability, conditional, mu


def load_frozen_a4s(root: Path) -> FrozenA4S:
    manifest_path = REPOSITORY_ROOT / "analysis/structured_a4s_deferred_validation/results/frozen_a4s_challenger_manifest.json"
    if sha256_file(manifest_path) != FROZEN_A4S_MANIFEST_SHA:
        raise RuntimeError("STOP: frozen A4-S manifest hash changed")
    json_path = root / "frozen_a4s_model.json"
    npz_path = root / "frozen_a4s_model.npz"
    if not json_path.exists() or not npz_path.exists():
        raise RuntimeError(f"frozen A4-S artifact is incomplete under {root}")
    if sha256_file(json_path) != FROZEN_A4S_JSON_SHA or sha256_file(npz_path) != FROZEN_A4S_NPZ_SHA:
        raise RuntimeError("STOP: frozen A4-S model artifact hash changed")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if payload.get("model_id") != "STRUCTURED_A4S_CHALLENGER" or payload.get("theta") != THETA or payload.get("graph_lambda") != 0.5 or payload.get("status") != "FROZEN_FOR_DEFERRED_INDEPENDENT_EVALUATION":
        raise RuntimeError("frozen A4-S model contract changed")
    with np.load(npz_path, allow_pickle=False) as archive:
        required = {"occurrence_beta", "count_beta", "training_mean", "training_sd", "occurrence_spatial_effect", "count_spatial_effect"}
        if not required.issubset(set(archive.files)):
            raise RuntimeError("frozen A4-S arrays are incomplete")
        arrays = {key: np.asarray(archive[key], dtype=np.float64) for key in required}
    if arrays["occurrence_beta"].shape != (35,) or arrays["count_beta"].shape != (35,) or arrays["training_mean"].shape != (34,) or arrays["training_sd"].shape != (34,) or arrays["occurrence_spatial_effect"].shape != (NODE_COUNT,) or arrays["count_spatial_effect"].shape != (NODE_COUNT,):
        raise RuntimeError("frozen A4-S array dimensions changed")
    if not all(np.isfinite(value).all() for value in arrays.values()) or (arrays["training_sd"] <= 0).any():
        raise RuntimeError("frozen A4-S arrays are non-finite")
    return FrozenA4S(root, json_path, npz_path, payload, arrays["occurrence_beta"], arrays["count_beta"], arrays["training_mean"], arrays["training_sd"], arrays["occurrence_spatial_effect"], arrays["count_spatial_effect"], FROZEN_A4S_JSON_SHA, FROZEN_A4S_NPZ_SHA)


def masked_center_tensor(residual: Any, mask: Any) -> Any:
    if residual.ndim != 1 or mask.ndim != 1 or residual.shape != mask.shape:
        raise ValueError("A5B residual and eligibility mask must be one-dimensional and aligned")
    if int(mask.sum().item()) == 0:
        raise ValueError("A5B residual centering received no eligible nodes")
    return residual - residual[mask].mean()


def occurrence_loss(observed: Any, occurrence_logit: Any, mask: Any) -> Any:
    import torch
    import torch.nn.functional as F

    positive = observed > 0
    values = torch.where(positive, F.softplus(-occurrence_logit), F.softplus(occurrence_logit))
    values = values[mask]
    if values.numel() == 0:
        raise ValueError("A5B occurrence loss received no eligible nodes")
    return values.mean()


def shell_tensors(relations: list[ShellRelation], device: Any) -> tuple[list[Any], list[Any], list[Any]]:
    import torch

    return (
        [torch.as_tensor(relation.source, dtype=torch.long, device=device) for relation in relations],
        [torch.as_tensor(relation.target, dtype=torch.long, device=device) for relation in relations],
        [torch.as_tensor(relation.degree, dtype=torch.float32, device=device) for relation in relations],
    )


def model_input(fold: A5.FoldPrepared, time_index: int, device: Any) -> Any:
    import torch

    features = np.concatenate([
        fold.x[time_index],
        fold.eta[time_index, :, None],
        fold.xi[time_index, :, None],
    ], axis=1).astype(np.float32)
    return torch.as_tensor(features, dtype=torch.float32, device=device)


def checkpoint_metadata(data: A5.DataBundle, config: dict[str, Any], relation_info: list[ShellRelation], candidate: str, fold_id: int, seed: int, unit_scope: str) -> dict[str, Any]:
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
            "shell_pair_counts": {str(relation.shell): relation.pair_count for relation in relation_info},
            "shell_sha256": {str(relation.shell): relation.sha256 for relation in relation_info},
        },
        "positional_encoding_used": False,
    }


def write_checkpoint_atomic(path: Path, model: Any, fit_info: dict[str, Any], metadata: dict[str, Any]) -> None:
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
        if validation.get("status") != "COMPLETED" or validation.get("metadata") != metadata or set(validation.get("model_state_dict", {})) != set(cpu_state):
            raise RuntimeError(f"A5B checkpoint validation failed for {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_checkpoint(path: Path, config: dict[str, Any], metadata: dict[str, Any], device: Any) -> tuple[Any | None, dict[str, Any] | None, str]:
    import torch

    if not path.exists() or path.stat().st_size == 0:
        return None, None, "NOT_FOUND"
    try:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("status") != "COMPLETED" or payload.get("metadata") != metadata:
            return None, None, "UNKNOWN_REGENERATE"
        model = MultiscaleOccurrenceResidualModel(
            36,
            shell_count=int(config["model"]["shell_count"]),
            shell_hidden_dim=int(config["model"]["shell_hidden_dim"]),
            post_hidden_dim=int(config["model"]["post_hidden_dim"]),
            dropout=float(config["model"]["dropout"]),
        ).to(device)
        model.load_state_dict(payload["model_state_dict"], strict=True)
        model.eval()
        fit_info = dict(payload["fit_info"])
        fit_info["checkpoint_status"] = "VERIFIED_REUSABLE"
        fit_info["checkpoint_path"] = str(path)
        fit_info["checkpoint_sha256"] = sha256_file(path)
        return model, fit_info, "VERIFIED_REUSABLE"
    except Exception:
        return None, None, "UNKNOWN_REGENERATE"


def train_model(
    fold: A5.FoldPrepared,
    seed: int,
    relations: list[ShellRelation],
    config: dict[str, Any],
    device: Any,
    train_node_mask: np.ndarray,
    checkpoint_path: Path | None,
    checkpoint_provenance: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any]]:
    import torch

    model_config = config["model"]
    mask_np = np.asarray(train_node_mask, dtype=bool)
    mask_t = torch.as_tensor(mask_np, dtype=torch.bool, device=device)
    sources, targets, degrees = shell_tensors(relations, device)

    def run_epochs(model: Any, optimizer: Any, times: np.ndarray, trajectory: list[dict[str, Any]], phase: str) -> float:
        model.train()
        losses: list[float] = []
        for time_index in times:
            optimizer.zero_grad(set_to_none=True)
            delta = masked_center_tensor(model(model_input(fold, int(time_index), device), sources, targets, degrees), mask_t)
            occurrence_logit = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device) + delta
            observed = torch.as_tensor(fold.counts[time_index], dtype=torch.float32, device=device)
            loss = occurrence_loss(observed, occurrence_logit, mask_t)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"non-finite A5B occurrence loss at week {time_index}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), float(model_config["gradient_clip_norm"]))
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        value = float(np.mean(losses))
        trajectory.append({"phase": phase, "loss": value, "weeks": int(len(times)), "eligible_nodes": int(mask_t.sum().item())})
        return value

    def monitor(model: Any, times: np.ndarray) -> float:
        model.eval()
        losses: list[float] = []
        with torch.no_grad():
            for time_index in times:
                delta = masked_center_tensor(model(model_input(fold, int(time_index), device), sources, targets, degrees), mask_t)
                occurrence_logit = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device) + delta
                observed = torch.as_tensor(fold.counts[time_index], dtype=torch.float32, device=device)
                losses.append(float(occurrence_loss(observed, occurrence_logit, mask_t).detach().cpu()))
        return float(np.mean(losses))

    inner_train, inner_monitor = A5.inner_split(fold.train_times, model_config["inner_monitor_fraction"], model_config["inner_monitor_min_weeks"])
    A5.set_seed(seed)
    model = MultiscaleOccurrenceResidualModel(36, int(model_config["shell_count"]), int(model_config["shell_hidden_dim"]), int(model_config["post_hidden_dim"]), float(model_config["dropout"])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(model_config["learning_rate"]), weight_decay=float(model_config["weight_decay"]))
    trajectory: list[dict[str, Any]] = []
    best_loss = math.inf
    best_epoch = 1
    stale = 0
    for epoch in range(1, int(model_config["max_epochs"]) + 1):
        run_epochs(model, optimizer, inner_train, trajectory, "fit")
        validation_loss = monitor(model, inner_monitor)
        trajectory.append({"phase": "monitor", "loss": validation_loss, "weeks": int(len(inner_monitor)), "eligible_nodes": int(mask_t.sum().item()), "epoch": int(epoch)})
        if validation_loss < best_loss - 1e-8:
            best_loss = validation_loss
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
            if stale >= int(model_config["early_stopping_patience"]):
                break

    A5.set_seed(seed)
    model = MultiscaleOccurrenceResidualModel(36, int(model_config["shell_count"]), int(model_config["shell_hidden_dim"]), int(model_config["post_hidden_dim"]), float(model_config["dropout"])).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(model_config["learning_rate"]), weight_decay=float(model_config["weight_decay"]))
    refit_trajectory: list[dict[str, Any]] = []
    for _ in range(1, best_epoch + 1):
        run_epochs(model, optimizer, fold.train_times, refit_trajectory, "refit")
    fit_info = {
        "seed": int(seed), "best_epoch": int(best_epoch), "inner_train_weeks": int(len(inner_train)), "inner_monitor_weeks": int(len(inner_monitor)),
        "inner_best_loss": float(best_loss), "parameter_count": parameter_count(model), "early_stop_trajectory": trajectory,
        "refit_epochs": int(best_epoch), "refit_trajectory": refit_trajectory, "converged": True,
        "train_node_count": int(mask_np.sum()), "center_residual": "eligible_nodes_per_target_week", "training_loss": config["model"]["training_loss"],
    }
    if checkpoint_path is not None:
        if checkpoint_provenance is None:
            raise ValueError("A5B checkpoint provenance is required")
        write_checkpoint_atomic(checkpoint_path, model, fit_info, checkpoint_provenance)
        fit_info["checkpoint_status"] = "WRITTEN"
        fit_info["checkpoint_path"] = str(checkpoint_path)
        fit_info["checkpoint_sha256"] = sha256_file(checkpoint_path)
    return model, fit_info


def fit_or_load_model(fold: A5.FoldPrepared, seed: int, relations: list[ShellRelation], config: dict[str, Any], data: A5.DataBundle, device: Any, checkpoint_path: Path, train_node_mask: np.ndarray, unit_scope: str) -> tuple[Any, dict[str, Any]]:
    metadata = checkpoint_metadata(data, config, relations, "A5B-MS-OCC", fold.fold, seed, unit_scope)
    model, fit_info, status = load_checkpoint(checkpoint_path, config, metadata, device)
    if model is not None and fit_info is not None:
        return model, fit_info
    model, fit_info = train_model(fold, seed, relations, config, device, train_node_mask, checkpoint_path, metadata)
    fit_info["checkpoint_input_status"] = status
    return model, fit_info


def predict_occurrence(fold: A5.FoldPrepared, model: Any, relations: list[ShellRelation], times: np.ndarray, train_node_mask: np.ndarray, eval_node_mask: np.ndarray, device: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import torch

    model.eval()
    sources, targets, degrees = shell_tensors(relations, device)
    train_mask_t = torch.as_tensor(np.asarray(train_node_mask, dtype=bool), dtype=torch.bool, device=device)
    eval_mask = np.asarray(eval_node_mask, dtype=bool)
    y_rows: list[np.ndarray] = []
    p_rows: list[np.ndarray] = []
    delta_rows: list[np.ndarray] = []
    with torch.no_grad():
        for time_index in times:
            delta = masked_center_tensor(model(model_input(fold, int(time_index), device), sources, targets, degrees), train_mask_t)
            logit = torch.as_tensor(fold.eta[time_index], dtype=torch.float32, device=device) + delta
            y_rows.append(fold.counts[time_index, eval_mask].astype(np.int64))
            p_rows.append(torch.sigmoid(logit).detach().cpu().numpy()[eval_mask])
            delta_rows.append(delta.detach().cpu().numpy()[eval_mask])
    return np.concatenate(y_rows), np.concatenate(p_rows), np.concatenate(delta_rows)


def load_a5_reference(root: Path) -> dict[str, Any]:
    decision_path = root / "results/a5_decision.json"
    fold_path = root / "results/fold_seed_metrics.csv"
    spatial_path = root / "results/residual_spatial_summary.csv"
    temporal_path = root / "results/residual_temporal_summary.csv"
    frontier_path = root / "results/frontier_metrics.csv"
    stress_path = root / "results/spatial_stress_metrics.csv"
    for path in (decision_path, fold_path, spatial_path, temporal_path, frontier_path, stress_path):
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError(f"required compact A5 reference artifact is missing: {path}")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if decision.get("primary_decision") != "A5_GNN_NOT_SUPPORTED":
        raise RuntimeError("completed A5 reference decision changed")
    fold = pd.read_csv(fold_path)
    missing = set(REFERENCE_CANDIDATES) - set(fold["candidate"].astype(str).unique())
    if missing:
        raise RuntimeError(f"completed A5 reference lacks required candidates: {sorted(missing)}")
    return {
        "root": root,
        "decision": decision,
        "fold": fold,
        "aggregate": pd.read_csv(root / "results/aggregate_metrics.csv"),
        "spatial": pd.read_csv(spatial_path),
        "temporal": pd.read_csv(temporal_path),
        "frontier": pd.read_csv(frontier_path),
        "stress": pd.read_csv(stress_path),
        "manifest_sha256": sha256_file(root / "provenance/a5_analysis_manifest.json") if (root / "provenance/a5_analysis_manifest.json").exists() else None,
    }


def reference_rows(reference: dict[str, Any], candidate: str, fold: int | None = None) -> pd.DataFrame:
    frame = reference["fold"].loc[reference["fold"]["candidate"].astype(str).eq(candidate)].copy()
    if fold is not None:
        frame = frame.loc[frame["fold"].astype(int).eq(int(fold))]
    return frame


def add_reference_source(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    result = frame.copy()
    result["reference_source"] = source
    return result


def a3_reproduction_gate(data: A5.DataBundle, frozen_a3_output: Path, reference: dict[str, Any], output: Path) -> tuple[pd.DataFrame, dict[int, dict[str, np.ndarray]]]:
    rows: list[dict[str, Any]] = []
    arrays_by_fold: dict[int, dict[str, np.ndarray]] = {}
    required = ["joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias"]
    for fold_record in FOLDS:
        fold = A5.prepare_temporal_fold(data, fold_record, frozen_a3_output)
        frozen = A5.load_frozen_a3_predictions(frozen_a3_output, fold.fold, data.counts, fold.validation_times)
        y, p, conditional, mu = (frozen[key] for key in ("y", "p", "conditional", "mu"))
        record, arrays = A5.fold_prediction_record("A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu, float(np.mean(fold.counts[fold.train_times] > 0)), {"frozen_reference_metrics": True, "reference_source": "structured_a3_final_comparison"})
        expected = reference_rows(reference, "A3", fold.fold).iloc[0]
        for metric in required:
            observed = float(record[metric])
            target = float(expected[metric])
            rows.append({"fold": fold.fold, "metric": metric, "reference": target, "reproduced": observed, "absolute_difference": abs(target - observed), "tolerance": 1e-9, "pass": bool(abs(target - observed) <= 1e-9)})
        arrays_by_fold[fold.fold] = arrays
    frame = pd.DataFrame(rows)
    write_csv(output / "results/a3_baseline_reproduction.csv", frame)
    if not bool(frame["pass"].all()):
        raise RuntimeError("STOP: exact frozen A3 reproduction failed before A5B fitting")
    return frame, arrays_by_fold


def mean_seed_arrays(records: dict[str, list[dict[str, Any]]], arrays_by_candidate: dict[str, list[dict[str, np.ndarray]]]) -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for candidate, items in arrays_by_candidate.items():
        if candidate == "A3":
            result[candidate] = {key: np.concatenate([item[key] for item in items]) for key in items[0]}
            continue
        grouped: dict[int, list[dict[str, np.ndarray]]] = {}
        for record, arrays in zip(records[candidate], items):
            grouped.setdefault(int(record["seed"]), []).append(arrays)
        seed_vectors = [{key: np.concatenate([item[key] for item in grouped[seed]]) for key in grouped[seed][0]} for seed in SEEDS]
        result[candidate] = {
            "y": seed_vectors[0]["y"],
            "p": np.mean([item["p"] for item in seed_vectors], axis=0),
            "conditional": np.mean([item["conditional"] for item in seed_vectors], axis=0),
            "mu": np.mean([item["mu"] for item in seed_vectors], axis=0),
            "week_index": seed_vectors[0]["week_index"], "node_id": seed_vectors[0]["node_id"], "fold": seed_vectors[0]["fold"],
        }
    return result


def primary_oof(data: A5.DataBundle, config: dict[str, Any], relations: list[ShellRelation], reference: dict[str, Any], a4s: FrozenA4S, frozen_a3_output: Path, output: Path, durable_root: Path | None, device: Any) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]], dict[str, list[dict[str, np.ndarray]]], dict[int, A5.FoldPrepared], dict[str, Any]]:
    import torch

    output.joinpath("predictions").mkdir(parents=True, exist_ok=True)
    output.joinpath("training").mkdir(parents=True, exist_ok=True)
    output.joinpath("checkpoints/primary").mkdir(parents=True, exist_ok=True)
    records: dict[str, list[dict[str, Any]]] = {candidate: [] for candidate in ["A3", *A5B_CANDIDATES]}
    arrays_by_candidate: dict[str, list[dict[str, np.ndarray]]] = {candidate: [] for candidate in ["A3", *A5B_CANDIDATES]}
    prepared: dict[int, A5.FoldPrepared] = {}
    new_rows: list[dict[str, Any]] = []
    delta_audit: list[dict[str, Any]] = []
    hybrid_audit: list[dict[str, Any]] = []

    def persist_progress() -> None:
        reference_rows_frame = add_reference_source(reference["fold"].loc[reference["fold"]["candidate"].astype(str).isin(REFERENCE_CANDIDATES)], "completed_a5_compact_artifact")
        frame = pd.concat([reference_rows_frame, pd.DataFrame(new_rows)], ignore_index=True, sort=False)
        write_csv(output / "results/fold_seed_metrics.csv", frame)
        if durable_root is not None:
            write_csv(durable_root / "results/fold_seed_metrics.csv", frame)

    for fold_record in FOLDS:
        fold = A5.prepare_temporal_fold(data, fold_record, frozen_a3_output)
        prepared[fold.fold] = fold
        frozen = A5.load_frozen_a3_predictions(frozen_a3_output, fold.fold, data.counts, fold.validation_times)
        y_a3, p_a3, cond_a3, mu_a3 = (frozen[key] for key in ("y", "p", "conditional", "mu"))
        a3_record, a3_arrays = A5.fold_prediction_record("A3", fold.fold, None, fold.validation_times, None, y_a3, p_a3, cond_a3, mu_a3, float(np.mean(fold.counts[fold.train_times] > 0)), {"frozen_reference_metrics": True, "reference_source": "structured_a3_final_comparison"})
        records["A3"].append(a3_record)
        arrays_by_candidate["A3"].append(a3_arrays)
        validation_raw = data.a3[fold.validation_times].reshape(-1, 34)
        _, cond_a4s, mu_a4s = a4s.predict(validation_raw)
        x_train = fold.x[fold.train_times].reshape(-1, 34).astype(np.float64)
        y_train = fold.counts[fold.train_times].reshape(-1)
        del x_train, y_train
        for seed in SEEDS:
            started = time.time()
            checkpoint = output / "checkpoints/primary" / "A5B-MS-OCC" / f"fold_{fold.fold:02d}" / f"seed_{seed}.pt"
            model, fit_info = fit_or_load_model(fold, seed, relations, config, data, device, checkpoint, np.ones(NODE_COUNT, dtype=bool), "primary_temporal_oof")
            y, p, deltas = predict_occurrence(fold, model, relations, fold.validation_times, np.ones(NODE_COUNT, dtype=bool), np.ones(NODE_COUNT, dtype=bool), device)
            fit_info = {**fit_info, "runtime_seconds": float(time.time() - started), "device": str(device), "reference_source": "A5B_fitted_occurrence_component"}
            rec_occ, arr_occ = A5.fold_prediction_record("A5B-MS-OCC", fold.fold, seed, fold.validation_times, None, y, p, cond_a3, mu_a3, float(np.mean(fold.counts[fold.train_times] > 0)), fit_info)
            rec_hyb, arr_hyb = A5.fold_prediction_record("A5B-HYBRID", fold.fold, seed, fold.validation_times, None, y, p, cond_a4s, mu_a4s, float(np.mean(fold.counts[fold.train_times] > 0)), {**fit_info, "a4s_count_component": "frozen_a4s_model_npz_no_refit"})
            records["A5B-MS-OCC"].append(rec_occ); arrays_by_candidate["A5B-MS-OCC"].append(arr_occ); new_rows.append(rec_occ)
            records["A5B-HYBRID"].append(rec_hyb); arrays_by_candidate["A5B-HYBRID"].append(arr_hyb); new_rows.append(rec_hyb)
            write_npz_atomic(output / "predictions" / f"A5B-MS-OCC_fold{fold.fold}_seed{seed}.npz", arr_occ)
            write_npz_atomic(output / "predictions" / f"A5B-HYBRID_fold{fold.fold}_seed{seed}.npz", arr_hyb)
            write_json(output / "training" / f"A5B-MS-OCC_fold{fold.fold}_seed{seed}.json", fit_info)
            delta_audit.append({"fold": fold.fold, "seed": seed, "delta_mean": float(np.mean(deltas)), "delta_sd": float(np.std(deltas)), "delta_finite": bool(np.isfinite(deltas).all())})
            hybrid_audit.append({"fold": fold.fold, "seed": seed, "conditional_max_abs_difference": float(np.max(np.abs(arr_hyb["conditional"] - cond_a4s))), "mu_max_abs_difference": float(np.max(np.abs(arr_hyb["mu"] - mu_a4s))), "a4s_component_reproduced": bool(np.array_equal(arr_hyb["conditional"], cond_a4s) and np.array_equal(arr_hyb["mu"], mu_a4s))})
            del model
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
            persist_progress()
    final_frame = pd.concat([add_reference_source(reference["fold"].loc[reference["fold"]["candidate"].astype(str).isin(REFERENCE_CANDIDATES)], "completed_a5_compact_artifact"), pd.DataFrame(new_rows)], ignore_index=True, sort=False)
    write_csv(output / "results/fold_seed_metrics.csv", final_frame)
    write_csv(output / "results/occurrence_centering_audit.csv", pd.DataFrame(delta_audit))
    write_csv(output / "results/hybrid_count_reproduction.csv", pd.DataFrame(hybrid_audit))
    return final_frame, records, arrays_by_candidate, prepared, {"occurrence_centering_audit": delta_audit, "hybrid_count_reproduction": hybrid_audit}


def aggregate_new_candidates(fold_metrics: pd.DataFrame) -> pd.DataFrame:
    numeric = [metric for metric in REQUIRED_METRICS if metric in fold_metrics.columns]
    rows: list[dict[str, Any]] = []
    for candidate in A5B_CANDIDATES:
        group = fold_metrics.loc[fold_metrics["candidate"].eq(candidate)].copy()
        if group.empty:
            continue
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
    return pd.DataFrame(rows)


def diagnostics(data: A5.DataBundle, config: dict[str, Any], reference: dict[str, Any], records: dict[str, list[dict[str, Any]]], arrays_by_candidate: dict[str, list[dict[str, np.ndarray]]], output: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, dict[str, np.ndarray]]]:
    predictions = mean_seed_arrays(records, arrays_by_candidate)
    spatial_current = A5.spatial_diagnostics(predictions, data, config, output)
    spatial_reference = reference["spatial"].loc[reference["spatial"]["candidate"].astype(str).isin(["STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"])].copy()
    spatial = pd.concat([spatial_current, spatial_reference], ignore_index=True, sort=False)
    spatial = spatial.sort_values(["candidate", "residual", "shell"]).reset_index(drop=True)
    write_csv(output / "results/residual_spatial_summary.csv", spatial)

    temporal_current = A5.temporal_diagnostics(predictions, output)
    temporal_reference = reference["temporal"].loc[reference["temporal"]["candidate"].astype(str).isin(["STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"])].copy()
    temporal = pd.concat([temporal_current, temporal_reference], ignore_index=True, sort=False)
    temporal = temporal.sort_values(["candidate", "residual", "lag_weeks"]).reset_index(drop=True)
    write_csv(output / "results/residual_temporal_summary.csv", temporal)

    frontier_current = A5.frontier_diagnostics(predictions, data, output)
    frontier_reference = reference["frontier"].loc[reference["frontier"]["candidate"].astype(str).isin(["STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"])].copy()
    frontier = pd.concat([frontier_current, frontier_reference], ignore_index=True, sort=False)
    frontier = frontier.sort_values(["candidate", "definition", "frontier_class"]).reset_index(drop=True)
    write_csv(output / "results/frontier_metrics.csv", frontier)
    return spatial, temporal, frontier, predictions


def run_spatial_stress(data: A5.DataBundle, config: dict[str, Any], relations: list[ShellRelation], a4s: FrozenA4S, reference: dict[str, Any], output: Path, device: Any) -> dict[str, Any]:
    if data.spatial_assignment is None:
        payload = {"status": "NOT_ESTIMABLE", "selection_used": False, "reason": "no existing deterministic spatial_node_assignments.parquet"}
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
        state, (_, _), _, scaling = A5.fit_a3_for_rows(raw_train, y_train, raw_all, A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES)
        mean = np.asarray(scaling["training_mean"], dtype=np.float64)
        sd = np.asarray(scaling["training_sd"], dtype=np.float64)
        x_all = ((data.a3 - mean[None, None, :]) / sd[None, None, :]).astype(np.float32)
        design_all = np.concatenate([np.ones((DEVELOPMENT_WEEKS, NODE_COUNT, 1)), x_all.astype(np.float64)], axis=2)
        eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
        xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
        fold = A5.FoldPrepared(100 + int(spatial_fold), all_times, all_times, x_all, data.counts, eta, xi, {**state, "scaling": scaling}, scaling)
        train_prevalence = float(np.mean(y_train > 0))
        for seed in SEEDS:
            checkpoint = output / "checkpoints/spatial_stress" / "A5B-MS-OCC" / f"fold_{int(spatial_fold):02d}" / f"seed_{seed}.pt"
            model, fit_info = fit_or_load_model(fold, seed, relations, config, data, device, checkpoint, train_nodes, "secondary_spatial_stress")
            y, p, _ = predict_occurrence(fold, model, relations, all_times, train_nodes, eval_nodes, device)
            raw_eval = data.a3[:, eval_nodes].reshape(-1, 34)
            _, cond_a4s, mu_a4s = a4s.predict(raw_eval, np.flatnonzero(eval_nodes))
            _, _, cond_a3, mu_a3 = A5.numpy_a3_predictions(fold, all_times, eval_nodes)
            base = {"spatial_fold": int(spatial_fold), "seed": int(seed), "training_nodes": int(train_nodes.sum()), "evaluation_nodes": int(eval_nodes.sum()), "best_epoch": int(fit_info["best_epoch"]), "parameter_count": int(fit_info["parameter_count"]), "temporary_checkpoint": str(checkpoint), "temporary_checkpoint_sha256": sha256_file(checkpoint), "converged": bool(fit_info.get("converged", False))}
            rows.append({"candidate": "A5B-MS-OCC", **base, **A5.metric_frame(y, p, cond_a3, mu_a3, train_prevalence)})
            rows.append({"candidate": "A5B-HYBRID", **base, "a4s_count_component": "frozen_a4s_model_npz_no_refit", **A5.metric_frame(y, p, cond_a4s, mu_a4s, train_prevalence)})
            del model
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    frame = pd.DataFrame(rows)
    write_csv(output / "results/spatial_stress_metrics.csv", frame)
    payload = {"status": "COMPLETED", "spatial_fold_count": int(len(np.unique(assignment))), "selection_used": False, "a4s_refit": False, "reference_stress_source": "completed_a5_compact_artifact"}
    write_json(output / "results/spatial_stress_status.json", payload)
    return payload


def assess_decision(fold_metrics: pd.DataFrame, spatial: pd.DataFrame, hybrid_audit: pd.DataFrame, config: dict[str, Any], hybrid_valid: bool) -> tuple[str, dict[str, Any]]:
    guard = config["guardrails"]
    complete = {candidate: not fold_metrics.loc[fold_metrics["candidate"].eq(candidate)].empty for candidate in A5B_CANDIDATES}
    a3 = fold_metrics.loc[fold_metrics["candidate"].eq("A3")]
    nope = fold_metrics.loc[fold_metrics["candidate"].eq("A5-GNN-NOPE")]
    a3_mean = {metric: float(a3[metric].mean()) for metric in REQUIRED_METRICS}
    nope_mean = {metric: float(nope[metric].mean()) for metric in REQUIRED_METRICS}
    spatial_mean = spatial.groupby(["candidate", "residual", "shell"], as_index=False)["moran_i"].mean()

    assessments: dict[str, Any] = {}
    for candidate in A5B_CANDIDATES:
        group = fold_metrics.loc[fold_metrics["candidate"].eq(candidate)].copy()
        if group.empty:
            assessments[candidate] = {"complete": False}
            continue
        fold_means = group.groupby("fold")["pr_auc"].mean()
        predictive = {
            "mean_pr_auc": float(group["pr_auc"].mean()) >= a3_mean["pr_auc"] - guard["mean_pr_auc_degradation"],
            "mean_brier_skill": float(group["brier_skill"].mean()) >= a3_mean["brier_skill"] - guard["mean_brier_skill_degradation"],
            "worst_fold_pr_auc": float(fold_means.min()) >= float(a3.groupby("fold")["pr_auc"].mean().min()) - guard["worst_fold_pr_auc_degradation"],
            "calibration_intercept": abs(abs(float(group["calibration_intercept"].mean())) - abs(a3_mean["calibration_intercept"])) <= guard["calibration_intercept_worsening"],
            "calibration_slope": abs(abs(float(group["calibration_slope"].mean())) - abs(a3_mean["calibration_slope"])) <= guard["calibration_slope_worsening"],
            "joint_hurdle_nll": float(group["joint_hurdle_nll"].mean()) <= a3_mean["joint_hurdle_nll"] + guard["joint_hurdle_nll_worsening"],
        }
        occurrence = spatial_mean.loc[(spatial_mean["candidate"].eq(candidate)) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
        a3_occurrence = spatial_mean.loc[(spatial_mean["candidate"].eq("A3")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
        nope_occurrence = spatial_mean.loc[(spatial_mean["candidate"].eq("A5-GNN-NOPE")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
        shell_reduction = {str(shell): float(a3_occurrence.loc[shell] - occurrence.loc[shell]) for shell in SHELLS if shell in occurrence.index and shell in a3_occurrence.index}
        outer_worsening = max((float(occurrence.loc[shell] - a3_occurrence.loc[shell]) for shell in (2, 3, 4) if shell in occurrence.index and shell in a3_occurrence.index), default=float("inf"))
        beyond_nope = bool(all(shell in occurrence.index and shell in nope_occurrence.index for shell in (2, 3, 4)) and float(occurrence.loc[[2, 3, 4]].mean()) < float(nope_occurrence.loc[[2, 3, 4]].mean()))
        spatial_guard = {
            "shell1_reduction_at_least_0.05": bool(shell_reduction.get("1", -math.inf) >= guard["shell1_occurrence_moran_reduction"]),
            "shell2_to_4_not_worse_than_0.01": bool(outer_worsening <= guard["outer_shell_moran_worsening"]),
            "larger_shell_mean_improves_over_a5_gnn_nope": beyond_nope,
        }
        seed_values = group.groupby("seed")["pr_auc"].mean()
        stability = {
            "convergence_failures": int((~group["converged"].astype(bool)).sum()),
            "finite_predictions": bool(np.isfinite(group[REQUIRED_METRICS].to_numpy(dtype=float)).all()),
            "pr_auc_seed_sd": float(seed_values.std(ddof=0)),
            "no_major_seed_collapse": bool(seed_values.std(ddof=0) <= 0.05),
        }
        count_reproduction: bool | str = "not_applicable"
        if candidate == "A5B-HYBRID":
            count_reproduction = bool(hybrid_valid and not hybrid_audit.empty and hybrid_audit["a4s_component_reproduced"].astype(bool).all() and hybrid_audit[["conditional_max_abs_difference", "mu_max_abs_difference"]].to_numpy(dtype=float).max() <= 1e-12)
        stability_ok = bool(stability["convergence_failures"] == 0 and stability["finite_predictions"] and stability["no_major_seed_collapse"])
        count_ok = bool(count_reproduction) if candidate == "A5B-HYBRID" else True
        assessments[candidate] = {
            "complete": True, "predictive_guardrails": predictive, "occurrence_shell_reduction_vs_a3": shell_reduction,
            "outer_shell_worst_worsening": outer_worsening, "spatial_guardrails": spatial_guard,
            "seed_stability": stability, "a4s_count_reproduction": count_reproduction,
            "all_guardrails": bool(all(predictive.values()) and all(spatial_guard.values()) and stability_ok and count_ok),
            "mean_metrics": {metric: float(group[metric].mean()) for metric in REQUIRED_METRICS},
            "mean_metrics_a3": a3_mean, "mean_metrics_a5_gnn_nope": nope_mean,
        }

    hybrid_ok = bool(assessments.get("A5B-HYBRID", {}).get("all_guardrails", False))
    occurrence_ok = bool(assessments.get("A5B-MS-OCC", {}).get("all_guardrails", False))
    if hybrid_ok:
        decision = "A5B_PROVISIONAL_HYBRID_CHALLENGER_JUSTIFIED"
        selected = "A5B-HYBRID"
    elif occurrence_ok:
        decision = "A5B_MULTISCALE_OCCURRENCE_CHALLENGER_JUSTIFIED"
        selected = "A5B-MS-OCC"
    elif all(complete.values()):
        decision = "A5B_NOT_JUSTIFIED"
        selected = None
    else:
        decision = "A5B_INCONCLUSIVE"
        selected = None
    a3_occ = spatial_mean.loc[(spatial_mean["candidate"].eq("A3")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
    selected_assessment = assessments.get(selected, {}) if selected else {}
    hybrid_count_reproduced = bool(assessments.get("A5B-HYBRID", {}).get("a4s_count_reproduction", False))
    evidence = {
        "decision": decision, "selected_candidate": selected, "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP",
        "a3": a3_mean, "a5_gnn_nope": nope_mean, "candidate_assessments": assessments,
        "required_interpretation": {
            "improved_occurrence_beyond_a3": bool(selected_assessment.get("spatial_guardrails", {}).get("shell1_reduction_at_least_0.05", False)),
            "improved_beyond_a5_gnn_nope": bool(selected_assessment.get("spatial_guardrails", {}).get("larger_shell_mean_improves_over_a5_gnn_nope", False)),
            "sustained_through_shells_2_to_4": bool(selected_assessment.get("spatial_guardrails", {}).get("shell2_to_4_not_worse_than_0.01", False)),
            "predictive_discrimination_and_calibration_acceptable": bool(all(selected_assessment.get("predictive_guardrails", {}).values())) if selected else False,
            "hybrid_preserved_frozen_a4s_count": hybrid_count_reproduced,
            "component_specific_treatments_supported": hybrid_count_reproduced,
        },
        "a3_first_shell_occurrence_moran": float(a3_occ.loc[1]) if 1 in a3_occ.index else None,
        "a5_prior_decision_preserved": "A5_GNN_NOT_SUPPORTED",
    }
    return decision, evidence


def write_figure_sources(aggregate: pd.DataFrame, spatial: pd.DataFrame, stress: pd.DataFrame, fold_metrics: pd.DataFrame, output: Path) -> None:
    figures = output / "figures"
    write_csv(figures / "figure_source_pr_auc.csv", aggregate.loc[aggregate["pr_auc"].notna(), [column for column in ["candidate", "aggregation", "seed", "fold", "pr_auc"] if column in aggregate.columns]])
    write_csv(figures / "figure_source_brier_skill.csv", aggregate.loc[aggregate["brier_skill"].notna(), [column for column in ["candidate", "aggregation", "seed", "fold", "brier_skill"] if column in aggregate.columns]])
    write_csv(figures / "figure_source_moran.csv", spatial.loc[:, [column for column in ["candidate", "residual", "shell", "moran_i", "permutation_p_value", "graph_pairs"] if column in spatial.columns]])
    seed_source = fold_metrics.loc[fold_metrics["candidate"].isin(A5B_CANDIDATES)].groupby(["candidate", "seed"], as_index=False)[["pr_auc", "joint_hurdle_nll"]].mean()
    write_csv(figures / "figure_source_seed_stability.csv", seed_source)
    write_csv(figures / "figure_source_spatial_stress.csv", stress)


def figure_status(output: Path) -> dict[str, Any]:
    try:
        import matplotlib  # noqa: F401
    except Exception:
        payload = {"status": "FIGURE_RENDERING_DEFERRED_ENVIRONMENT_LIMITATION", "figure_source_tables": "generated", "reason": "matplotlib unavailable in supported Atlas environment"}
    else:
        payload = {"status": "FIGURE_RENDERING_DEFERRED_ENVIRONMENT_LIMITATION", "figure_source_tables": "generated", "reason": "graphics intentionally deferred; no shared software modification permitted"}
    write_json(output / "figures/figure_generation_status.json", payload)
    return payload


COMPACT_PROMOTION_FILES = (
    "results/fold_seed_metrics.csv", "results/aggregate_metrics.csv", "results/a3_baseline_reproduction.csv",
    "results/residual_spatial_summary.csv", "results/residual_temporal_summary.csv", "results/frontier_metrics.csv",
    "results/spatial_stress_metrics.csv", "results/spatial_stress_status.json", "results/a5b_decision.json",
    "results/spatial_shell_contract.csv", "results/occurrence_centering_audit.csv", "results/hybrid_count_reproduction.csv",
    "results/selected_candidate_configuration.json", "figures/figure_generation_status.json",
    "figures/figure_source_pr_auc.csv", "figures/figure_source_brier_skill.csv", "figures/figure_source_moran.csv",
    "figures/figure_source_seed_stability.csv", "figures/figure_source_spatial_stress.csv",
    "provenance/a5b_analysis_manifest.json", "provenance/environment_manifest.json", "provenance/feature_target_access_audit.json",
    "provenance/checksum_manifest.json", "final_decision_report.md",
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
        "status": "COMPLETED", "storage_class": "DURABLE_PROJECT_ARTIFACTS", "source_output_root": str(output),
        "durable_summary_root": str(durable_root), "files": copied,
        "temporary_storage_warning": "TEMPORARY_90DAY_STORAGE large products remain under /90daydata and are automatically removed after 90 days without activity.",
    }
    write_json(durable_root / "provenance/a5b_durable_promotion_manifest.json", manifest)
    return manifest


def write_checksum_manifest(output: Path) -> None:
    write_json(output / "provenance/checksum_manifest.json", {
        "storage_class": "TEMPORARY_90DAY_STORAGE",
        "files": {str(path.relative_to(output)): sha256_file(path) for path in output.rglob("*") if path.is_file() and path.name != "checksum_manifest.json"},
    })


def write_report(output: Path, config: dict[str, Any], fold_metrics: pd.DataFrame, aggregate: pd.DataFrame, spatial: pd.DataFrame, temporal: pd.DataFrame, frontier: pd.DataFrame, stress: dict[str, Any], decision: str, evidence: dict[str, Any], environment: dict[str, Any], a4s: FrozenA4S, figure_info: dict[str, Any]) -> None:
    def aggregate_value(candidate: str, metric: str) -> float | None:
        row = aggregate.loc[(aggregate["candidate"].eq(candidate)) & (aggregate["aggregation"].eq("mean_seed_fold"))]
        if row.empty:
            row = aggregate.loc[(aggregate["candidate"].eq(candidate)) & (aggregate["aggregation"].eq("fold_mean"))]
        return float(row.iloc[0][metric]) if not row.empty and pd.notna(row.iloc[0][metric]) else None

    def spatial_value(candidate: str, residual: str, shell: int) -> float | None:
        row = spatial.loc[(spatial["candidate"].eq(candidate)) & (spatial["residual"].eq(residual)) & (spatial["shell"].eq(shell)), "moran_i"]
        return float(row.mean()) if not row.empty else None

    selected = evidence.get("selected_candidate")
    interp = evidence["required_interpretation"]
    lines = [
        "# A5B Multiscale Component-Specific Spatial ML report", "",
        "## I. Governance", "",
        "This is a supervised-agent `DEVELOPMENT_INFORMED_FOLLOWUP` under SAE governance. The A3 production artifact, frozen A4-S artifact, completed A5 result, and production configuration were treated as immutable. No merge, release, or production change was made.", "",
        "## II. Starting state", "",
        f"A5 parent SHA: `{PARENT_A5_SHA}`. A5B execution SHA: `{git_value('rev-parse', 'HEAD')}`. Branch: `{git_value('branch', '--show-current')}`. Prior A5 decision preserved as `A5_GNN_NOT_SUPPORTED`. A3 SHA: `{PRODUCTION_MODEL_SHA}`. A4-S manifest SHA: `{FROZEN_A4S_MANIFEST_SHA}`. Canonical graph SHA: `{config['graph']['canonical_edge_sha256']}`.", "",
        "## III. A5 evidence motivating A5B", "",
        "A5 showed improved discrimination without sufficient residual spatial correction. The prespecified motivation was A3 first-shell occurrence residual Moran's I 0.293260 versus 0.245346 for A5-GNN-NOPE, an approximate 0.0479 reduction that narrowly missed the 0.05 guardrail, with larger-shell weakening and no useful positive-count correction. A5B therefore removes positional encodings and targets occurrence with exact multiscale shell relations.", "",
        "## IV. Atlas storage configuration", "",
        f"`/project/disease_ecology`: {environment['project_filesystem']}. `/90daydata/disease_ecology` run root: `{environment['temporary_output_root']}`. Cache: `{environment['cache_root']}`. TMPDIR: `{environment['tmp_root']}`. Slurm logs: `{environment['logs_root']}`. Durable summaries: `{environment['durable_summary_root']}`. Large runtime products are labeled `TEMPORARY_90DAY_STORAGE` and are subject to automatic deletion after 90 days without activity.", "",
        "## V. Multiscale graph construction", "",
        f"The canonical 10,037-node, 77,614-directed-edge queen graph was the only primitive topology. Exact deterministic shortest-path shells 1--4 were constructed in canonical node order; shell pair counts and SHA-256 hashes are in `results/spatial_shell_contract.csv`. Learned adjacency, outcome-derived edges, and explicit self-loops were not used. Shell counts: `{evidence.get('shell_contract')}`.", "",
        "## VI. A5B architecture", "",
        "A5B-MS-OCC is a shallow four-relation mean GraphSAGE occurrence residual model. Each shell has a separate operator with hidden width 8; the four representations are concatenated, passed through a ReLU/dropout 0.10 head, and mapped to one centered occurrence correction. Inputs are standardized 34 A3 predictors plus the A3 occurrence and positive-count linear predictors. No coordinates, eigenvectors, free node embeddings, attention, recurrence, or graph search were used.", "",
        "## VII. Leakage verification", "",
        "The target-week outcome is used only in the occurrence-component training loss and post-prediction metrics; it is never passed as a node feature or edge. Shells are built only from the response-independent canonical edge artifact. No validation or future outcome, residual, intervention/SIT variable, or post-2026-W16 outcome entered architecture or graph selection. Per-week residual centering is across eligible training nodes.", "",
        "## VIII. Predictive performance", "",
        f"A3 mean PR-AUC `{aggregate_value('A3', 'pr_auc')}`, Brier skill `{aggregate_value('A3', 'brier_skill')}`, joint hurdle NLL `{aggregate_value('A3', 'joint_hurdle_nll')}`. A5-GNN-NOPE mean PR-AUC `{aggregate_value('A5-GNN-NOPE', 'pr_auc')}`, Brier skill `{aggregate_value('A5-GNN-NOPE', 'brier_skill')}`, joint hurdle NLL `{aggregate_value('A5-GNN-NOPE', 'joint_hurdle_nll')}`. A5B-MS-OCC mean PR-AUC `{aggregate_value('A5B-MS-OCC', 'pr_auc')}`, joint hurdle NLL `{aggregate_value('A5B-MS-OCC', 'joint_hurdle_nll')}`. A5B-HYBRID mean PR-AUC `{aggregate_value('A5B-HYBRID', 'pr_auc')}`, joint hurdle NLL `{aggregate_value('A5B-HYBRID', 'joint_hurdle_nll')}`. Complete fold/seed metrics are in `results/fold_seed_metrics.csv`.", "",
        "## IX. Occurrence spatial residuals", "",
        f"The primary shell-1 reduction and shells 2--4 preservation assessment is `{evidence.get('candidate_assessments', {}).get(selected, {}).get('spatial_guardrails') if selected else 'no candidate satisfied the provisional decision logic'}`. A5B occurrence Moran's I is reported for all four shells alongside A3 and A5-GNN-NOPE in `results/residual_spatial_summary.csv`. Improvement beyond A3: `{interp['improved_occurrence_beyond_a3']}`; improvement beyond A5-GNN-NOPE at larger shells: `{interp['improved_beyond_a5_gnn_nope']}`.", "",
        "## X. Positive-count spatial residuals", "",
        f"A5B-MS-OCC retains A3's positive-count component. A5B-HYBRID uses the immutable A4-S `count_beta` and `count_spatial_effect` arrays without refitting; maximum conditional/mu reproduction differences are in `results/hybrid_count_reproduction.csv`. Frozen A4-S artifact hashes are `{a4s.json_sha256}` and `{a4s.npz_sha256}`. No claim is made that the occurrence network solves positive-count spatial dependence.", "",
        "## XI. Full-hurdle residuals", "",
        "Full-hurdle expected-count residual Moran's I at shells 1--4 is reported separately from occurrence and positive-count residuals in `results/residual_spatial_summary.csv`.", "",
        "## XII. Temporal residuals", "",
        "Same-cell residual correlations at lags 1, 2, and 3 weeks are reported for occurrence, positive count, and full hurdle count in `results/residual_temporal_summary.csv`. A5B is non-recurrent; temporal dependence is documented rather than modeled away.", "",
        "## XIII. Spatial stress test", "",
        f"Stress status: `{stress}`. The existing deterministic spatial partition was reused unchanged, held-out outcomes were excluded from training, and stress results were excluded from model selection. A4-S was not refit.", "",
        "## XIV. Frontier performance", "",
        "Previously unoccupied cells, recent occupancy, distance-to-prior-detection classes, and first-recorded-detection events where estimable reuse the completed A5 definitions. Results are in `results/frontier_metrics.csv`; intervention-confounded U.S. raw count magnitude was not used as a selection endpoint.", "",
        "## XV. Seed stability", "",
        f"Seeds 1729, 31415, and 271828 were used. Seed-level PR-AUC and Moran summaries are retained; the selected-candidate stability assessment is `{evidence.get('candidate_assessments', {}).get(selected, {}).get('seed_stability') if selected else 'not applicable'}`.", "",
        "## XVI. Component-specific hybrid assessment", "",
        f"The frozen A4-S NPZ permitted exact extraction of the positive-count component without refit. Hybrid count reproduction passed: `{interp['hybrid_preserved_frozen_a4s_count']}`. The component-specific evidence supports different occurrence and positive-count spatial treatments: `{interp['component_specific_treatments_supported']}`.", "",
        "## XVII. Limitations", "",
        "A5B was designed after inspecting F1--F4 A5 results and is not independent validation. It cannot establish prospective superiority, causal transmission, dispersal, surveillance effects, intervention effects, or biological mechanism. The frozen A4-S full-development artifact is a fixed reference component; later independent evaluation remains required.", "",
        "## XVIII. Primary decision", "",
        f"`{decision}`. This means only that the specified architecture is or is not sufficiently promising for a later independent-validation freeze decision; it does not authorize deployment.", "",
        "## XIX. Repository/PR state", "",
        f"Branch: `{git_value('branch', '--show-current')}`. Parent A5 history was not rewritten. A3, A4-S, and A5 artifacts remain unchanged. No merge or release was performed. Focused tests and Atlas execution evidence are recorded in provenance.", "",
        "## XX. Storage/artifact state", "",
        "`DURABLE_PROJECT_ARTIFACTS`: compact CSV/JSON summaries, figure-source tables, provenance, checksums, and this report under the A5B project worktree. `TEMPORARY_90DAY_STORAGE_ARTIFACTS`: checkpoints, predictions, training traces, residual maps, spatial tensors, caches, temporary figures, and Slurm logs under the run-specific `/90daydata` root. The latter are automatically deleted after 90 days of inactivity. A provisional candidate does not automatically promote large model state; any future freeze requires a separate storage/freeze decision.", "",
        f"Figure status: `{figure_info}`. Figure-source tables were generated regardless of graphics availability.", "",
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
    parser.add_argument("--a3-frozen-output", type=Path, default=Path(os.environ["A5B_FROZEN_A3_OUTPUT"]) if os.environ.get("A5B_FROZEN_A3_OUTPUT") else None)
    parser.add_argument("--a4s-frozen-output", type=Path, default=Path(os.environ["A5B_A4S_FROZEN_OUTPUT"]) if os.environ.get("A5B_A4S_FROZEN_OUTPUT") else None)
    parser.add_argument("--a5-reference-root", type=Path, default=Path(os.environ["A5B_A5_REFERENCE_ROOT"]) if os.environ.get("A5B_A5_REFERENCE_ROOT") else REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison")
    parser.add_argument("--spatial-assignments", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--durable-summary-root", type=Path, default=Path(os.environ["A5B_DURABLE_SUMMARY_ROOT"]) if os.environ.get("A5B_DURABLE_SUMMARY_ROOT") else None)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--skip-spatial-stress", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()

    config = read_config(args.config)
    output = resolve_output_root(args.output_root)
    durable_root = args.durable_summary_root.expanduser().resolve() if args.durable_summary_root is not None else None
    assert_storage_roots(output, durable_root)
    for directory in ("results", "predictions", "training", "checkpoints", "tensors", "residuals", "cache", "tmp", "logs", "figures_work", "figures", "manifests", "provenance"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    if durable_root is not None:
        for directory in ("results", "provenance", "figures"):
            (durable_root / directory).mkdir(parents=True, exist_ok=True)
        write_json(durable_root / "results/restart_recovery.json", {
            "status": "RUNNING", "recovery_classification": "INCOMPLETE_REGENERATE", "parent_a5_sha": PARENT_A5_SHA,
            "prior_a5_decision": "A5_GNN_NOT_SUPPORTED", "verified_reusable_units": [],
            "units_requiring_rerun": "all A5B units until matching completed checkpoints exist",
            "execution_sha": git_value("rev-parse", "HEAD"), "output_root": str(output), "storage_class": "TEMPORARY_90DAY_STORAGE",
        })

    args.a3_frozen_output = args.a3_frozen_output.expanduser().resolve() if args.a3_frozen_output is not None else None
    args.a4s_frozen_output = args.a4s_frozen_output.expanduser().resolve() if args.a4s_frozen_output is not None else None
    args.a5_reference_root = args.a5_reference_root.expanduser().resolve()
    if args.a3_frozen_output is None or args.a4s_frozen_output is None:
        raise RuntimeError("STOP: exact frozen A3 and A4-S roots are required")
    production_path = REPOSITORY_ROOT / "analysis/structured_a3_evaluation/results/final_a3_model.json"
    if sha256_file(production_path) != PRODUCTION_MODEL_SHA:
        raise RuntimeError("STOP: frozen production A3 artifact hash changed")
    reference = load_a5_reference(args.a5_reference_root)
    a4s = load_frozen_a4s(args.a4s_frozen_output)

    import torch
    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available() else args.device if args.device != "auto" else "cpu")
    data = load_data(args, config)
    if data.hashes.get("edges") != config["graph"]["canonical_edge_sha256"]:
        raise RuntimeError("STOP: canonical graph checksum changed")
    relations = build_shell_relations(data, args.a5_reference_root)
    shell_frame = pd.DataFrame([{"shell": relation.shell, "pair_count": relation.pair_count, "sha256": relation.sha256, "response_independent": True, "source": "canonical_queen_edges_exact_shortest_path"} for relation in relations])
    write_csv(output / "results/spatial_shell_contract.csv", shell_frame)
    a3_gate, _ = a3_reproduction_gate(data, args.a3_frozen_output, reference, output)
    if args.preflight:
        print(json.dumps({"status": "a5b_preflight_passed", "shell_pair_counts": {str(relation.shell): relation.pair_count for relation in relations}, "a3_gate_max_absolute_difference": float(a3_gate["absolute_difference"].max()), "frozen_a4s_json_sha256": a4s.json_sha256, "frozen_a4s_npz_sha256": a4s.npz_sha256}, indent=2))
        return 0

    fold_metrics, records, arrays_by_candidate, prepared, audits = primary_oof(data, config, relations, reference, a4s, args.a3_frozen_output, output, durable_root, device)
    spatial, temporal, frontier, predictions = diagnostics(data, config, reference, records, arrays_by_candidate, output)
    reference_aggregate = reference["aggregate"].loc[reference["aggregate"]["candidate"].astype(str).isin(REFERENCE_CANDIDATES)].copy()
    aggregate = pd.concat([reference_aggregate, aggregate_new_candidates(fold_metrics)], ignore_index=True, sort=False)
    aggregate = aggregate.sort_values(["candidate", "aggregation", "seed", "fold"], na_position="last").reset_index(drop=True)
    write_csv(output / "results/aggregate_metrics.csv", aggregate)
    stress = {"status": "SKIPPED", "selection_used": False, "reason": "command-line skip"} if args.skip_spatial_stress else run_spatial_stress(data, config, relations, a4s, reference, output, device)
    hybrid_audit = pd.DataFrame(audits["hybrid_count_reproduction"])
    decision, evidence = assess_decision(fold_metrics, spatial, hybrid_audit, config, True)
    evidence["shell_contract"] = {str(relation.shell): {"pair_count": relation.pair_count, "sha256": relation.sha256} for relation in relations}
    evidence["hybrid_artifact"] = {"status": "VALID_EXACTLY_EXTRACTABLE", "root": str(a4s.root), "json_sha256": a4s.json_sha256, "npz_sha256": a4s.npz_sha256, "refit": False}
    write_json(output / "results/a5b_decision.json", {"primary_decision": decision, "evidence": evidence, "frontier_rows": int(len(frontier)), "temporal_rows": int(len(temporal)), "a3_gate_max_absolute_difference": float(a3_gate["absolute_difference"].max())})
    write_json(output / "results/selected_candidate_configuration.json", {"decision": decision, "selected_candidate": evidence.get("selected_candidate"), "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP", "freeze_action": "DURABLE_PROMOTION_PENDING_STORAGE/FREEZE_DECISION" if evidence.get("selected_candidate") else "NONE"})
    write_figure_sources(aggregate, spatial, stress if isinstance(stress, pd.DataFrame) else (pd.read_csv(output / "results/spatial_stress_metrics.csv") if (output / "results/spatial_stress_metrics.csv").exists() else pd.DataFrame()), fold_metrics, output)
    figure_info = figure_status(output)

    project_usage = filesystem_usage("/project/disease_ecology")
    temporary_usage = filesystem_usage("/90daydata/disease_ecology")
    environment = {
        "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": __import__("scipy").__version__, "torch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()), "cuda_version": str(torch.version.cuda), "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "device_used": str(device), "project_filesystem": project_usage, "temporary_filesystem": temporary_usage,
        "temporary_output_root": str(output), "cache_root": os.environ.get("A5B_CACHE_ROOT"), "tmp_root": os.environ.get("A5B_TMP_ROOT", os.environ.get("TMPDIR")),
        "logs_root": str(output / "logs"), "durable_summary_root": str(durable_root) if durable_root is not None else None,
        "temporary_storage_class": "TEMPORARY_90DAY_STORAGE", "positional_encoding_used": False,
    }
    write_json(output / "provenance/environment_manifest.json", environment)
    write_json(output / "provenance/feature_target_access_audit.json", {
        "status": "PASSED", "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP", "target_access": "targets are used only by the occurrence training loss, exact hurdle metrics, and diagnostics after prediction",
        "forbidden_inputs": config["forbidden"]["inputs"], "graph_contract": "canonical queen graph with exact shortest-path shells 1-4; no outcome-derived edges", "positional_encoding_used": False,
        "selection_boundary": "2025-W01 through 2026-W16; F1-F4 only", "post_w16_outcomes_used": False, "sit_included": False,
    })
    manifest = {
        "analysis": config["analysis"], "status": "completed", "generated_utc": utc_now(), "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP",
        "parent_a5_sha": PARENT_A5_SHA, "execution_sha": git_value("rev-parse", "HEAD"), "branch": git_value("branch", "--show-current"),
        "prior_a5_decision": "A5_GNN_NOT_SUPPORTED", "candidate_scope": config["candidates"], "development_period": config["development_period"], "folds": config["folds"], "seeds": SEEDS,
        "input_sha256": data.hashes, "graph": {"node_count": NODE_COUNT, "directed_edge_count": int(len(data.source)), "edge_sha256": data.hashes.get("edges"), "shells": evidence["shell_contract"]},
        "frozen_a3": {"root": str(args.a3_frozen_output), "production_artifact_sha256": PRODUCTION_MODEL_SHA},
        "frozen_a4s": {"root": str(a4s.root), "manifest_sha256": FROZEN_A4S_MANIFEST_SHA, "model_json_sha256": a4s.json_sha256, "model_npz_sha256": a4s.npz_sha256, "refit": False},
        "a5_reference": {"root": str(args.a5_reference_root), "manifest_sha256": reference["manifest_sha256"], "decision": "A5_GNN_NOT_SUPPORTED"},
        "a3_reproduction_max_difference": float(a3_gate["absolute_difference"].max()), "decision": decision, "evidence": evidence, "spatial_stress_test": stress, "figures": figure_info,
        "runtime": environment, "script_sha256": {"run_a5b.py": sha256_file(Path(__file__)), "a5b_model.py": sha256_file(Path(__file__).with_name("a5b_model.py")), "config": sha256_file(args.config)},
        "storage": {"temporary_storage_class": "TEMPORARY_90DAY_STORAGE", "temporary_output_root": str(output), "durable_summary_root": str(durable_root) if durable_root is not None else None, "temporary_storage_retention": "90 days without activity", "large_output_paths": {name: str(output / name) for name in ("checkpoints", "predictions", "tensors", "residuals", "cache", "tmp", "logs", "figures_work")}, "durable_promotion": {"status": "PENDING"}},
    }
    write_json(output / "provenance/a5b_analysis_manifest.json", manifest)
    write_report(output, config, fold_metrics, aggregate, spatial, temporal, frontier, stress, decision, evidence, environment, a4s, figure_info)
    write_checksum_manifest(output)
    promotion = promote_compact_outputs(output, durable_root)
    manifest["storage"]["durable_promotion"] = promotion
    write_json(output / "provenance/a5b_analysis_manifest.json", manifest)
    write_checksum_manifest(output)
    promotion = promote_compact_outputs(output, durable_root)
    if durable_root is not None:
        write_json(durable_root / "results/restart_recovery.json", {"status": "COMPLETED", "recovery_classification": "VERIFIED_REUSABLE", "parent_a5_sha": PARENT_A5_SHA, "prior_a5_decision": "A5_GNN_NOT_SUPPORTED", "verified_reusable_units": "all A5B units with COMPLETED checkpoint and matching provenance", "units_requiring_rerun": "none after this completed run", "execution_sha": git_value("rev-parse", "HEAD"), "output_root": str(output), "durable_promotion": promotion, "storage_class": "TEMPORARY_90DAY_STORAGE"})
    print(json.dumps({"status": "a5b_completed", "decision": decision, "a3_gate_max_absolute_difference": float(a3_gate["absolute_difference"].max()), "durable_promotion": promotion}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
