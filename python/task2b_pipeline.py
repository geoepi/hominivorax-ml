#!/usr/bin/env python3
"""Task-2B development-only recurrent hurdle-NB training and evaluation.

This module intentionally consumes the Task-2A arrays and persisted split
definitions.  It never scores the final test weeks in ``development`` mode.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from scipy.special import gammaln

from hurdle_zt_nb import zt_nb_positive_mean
from task2b_models import GConvGRUHurdleNB, GRUHurdleNB


ENV_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
]
DENSITY_FEATURES = ["cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"]
INDICATOR_FEATURES = [f"{name}_imputed" for name in DENSITY_FEATURES]
CALENDAR_FEATURES = ["week_sin", "week_cos"]
FEATURES = ENV_FEATURES + DENSITY_FEATURES + INDICATOR_FEATURES + CALENDAR_FEATURES
PERIOD = 52.1775
N_CONTEXT = 52
EPS = 1e-8


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, torch.Tensor): return value.detach().cpu().tolist()
    if isinstance(value, dict): return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [jsonable(v) for v in value]
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


def load_data(root: Path) -> dict[str, Any]:
    model_root = root / "model_data"
    raw = model_root / "raw"
    return {
        "root": root,
        "model_root": model_root,
        "raw": raw,
        "manifest": json.loads((model_root / "manifests/dataset_manifest.json").read_text()),
        "dynamic": np.load(raw / "dynamic_features.npy", mmap_mode="r"),
        "history": np.load(raw / "dynamic_history_features.npy", mmap_mode="r"),
        "static": np.load(raw / "static_features.npy", mmap_mode="r"),
        "counts": np.load(raw / "targets_count.npy", mmap_mode="r"),
        "presence": np.load(raw / "targets_presence.npy", mmap_mode="r"),
        "weeks": pd.read_parquet(raw / "weeks.parquet"),
        "calendar": pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float32),
        "nodes": pd.read_parquet(raw / "nodes.parquet"),
        "edges": pd.read_parquet(raw / "edges_queen.parquet"),
        "splits": json.loads((model_root / "splits/temporal_splits.json").read_text()),
        "spatial": pd.read_parquet(model_root / "splits/spatial_node_assignments.parquet"),
    }


def assert_dataset(data: dict[str, Any]) -> None:
    expected = {
        "dynamic": (133, 16756, 12), "history": (185, 16756, 12),
        "static": (16756, 10), "counts": (133, 16756), "presence": (133, 16756),
    }
    actual = {key: tuple(data[key].shape) for key in expected}
    if actual != expected: raise AssertionError(f"Task-2A shape mismatch: {actual}")
    if not np.array_equal(np.asarray(data["presence"]), np.asarray(data["counts"]) > 0):
        raise AssertionError("presence does not equal count > 0")
    if np.any(np.asarray(data["counts"]) < 0): raise AssertionError("negative count")
    if not np.isfinite(np.asarray(data["dynamic"])).all() or not np.isfinite(np.asarray(data["static"])).all():
        raise AssertionError("non-finite raw predictor")
    if not np.all(np.asarray(data["static"])[:, :5] >= 0): raise AssertionError("negative livestock density")
    if not np.all(np.isin(np.asarray(data["static"])[:, 5:], [0, 1])): raise AssertionError("invalid imputation indicator")
    if not np.array_equal(data["nodes"]["node_id"].to_numpy(), np.arange(16756)):
        raise AssertionError("node IDs are not zero-based contiguous")
    edges = data["edges"][["source_node", "target_node"]].to_numpy(np.int64)
    if edges.size and (edges.min() < 0 or edges.max() >= 16756): raise AssertionError("edge index out of bounds")


def make_calendar(data: dict[str, Any]) -> np.ndarray:
    """Return 52-week environmental-context calendar followed by target calendar."""
    target = np.asarray(data["calendar"], dtype=np.float32)
    index = np.arange(-N_CONTEXT, len(target), dtype=np.float64)
    context = np.column_stack([np.sin(2 * np.pi * index / PERIOD), np.cos(2 * np.pi * index / PERIOD)]).astype(np.float32)
    # Target values are taken from the frozen artifact; this is a consistency check.
    if not np.allclose(context[N_CONTEXT:], target, atol=2e-5):
        raise AssertionError("Task-2A calendar values do not match the approved continuous index")
    return context


def fit_preprocessor(data: dict[str, Any], train_indices: list[int], spatial_fold: int | None = None) -> dict[str, Any]:
    """Fit fold-aware transforms; indicators and calendar remain 0/1 and [-1,1]."""
    dynamic = np.asarray(data["dynamic"][train_indices], dtype=np.float64).reshape(-1, 12)
    static = np.asarray(data["static"], dtype=np.float64)
    density = np.log1p(static[:, :5])
    indicator = static[:, 5:]
    cal = np.asarray(data["calendar"][train_indices], dtype=np.float64)
    density_rows = np.tile(density, (len(train_indices), 1))
    indicator_rows = np.tile(indicator, (len(train_indices), 1))
    cal_rows = np.repeat(cal, len(static), axis=0)
    values = np.column_stack([dynamic, density_rows, indicator_rows, cal_rows])
    mean = values.mean(axis=0)
    scale = values.std(axis=0)
    # The contract says to preserve binary/calendar interpretation.
    mean[17:] = 0.0
    scale[17:] = 1.0
    scale[:17][(~np.isfinite(scale[:17])) | (scale[:17] == 0)] = 1.0
    return {
        "feature_names": FEATURES,
        "transform": {name: ("log1p" if name in DENSITY_FEATURES else "identity") for name in FEATURES},
        "training_week_indices": train_indices,
        "spatial_fold_excluded": spatial_fold,
        "mean": mean.tolist(), "standard_deviation": scale.tolist(),
        "indicators_unscaled": True, "calendar_unscaled": True,
    }


def apply_preprocessor(data: dict[str, Any], prep: dict[str, Any]) -> np.ndarray:
    dynamic = np.asarray(data["history"], dtype=np.float32)
    static = np.asarray(data["static"], dtype=np.float32)
    density = np.log1p(static[:, :5]).astype(np.float32)
    indicator = static[:, 5:]
    cal = make_calendar(data)
    n_time = dynamic.shape[0]
    stat = np.tile(np.concatenate([density, indicator], axis=1)[None, :, :], (n_time, 1, 1))
    cal_rows = np.repeat(cal[:, None, :], static.shape[0], axis=1)
    features = np.concatenate([dynamic, stat, cal_rows], axis=2).astype(np.float32)
    mean = np.asarray(prep["mean"], dtype=np.float32)
    scale = np.asarray(prep["standard_deviation"], dtype=np.float32)
    return (features - mean[None, None, :]) / scale[None, None, :]


def split_indices(data: dict[str, Any], fold: int) -> tuple[list[int], list[int]]:
    for record in data["splits"]["temporal_folds"]:
        if int(record["fold"]) == fold:
            return record["train_indices"], record["validation_indices"]
    raise KeyError(f"unknown temporal fold {fold}")


def assert_development_only(mask: np.ndarray, data: dict[str, Any], evaluation_mode: str) -> None:
    if evaluation_mode != "development": return
    test_indices = np.asarray(data["splits"]["final_test"]["indices"], dtype=np.int64)
    if mask.ndim == 1 and np.any(mask[test_indices]):
        raise RuntimeError("development mode prohibits final-test predictive metrics")
    if mask.ndim == 2 and np.any(mask[test_indices, :]):
        raise RuntimeError("development mode prohibits final-test predictive metrics")


def exact_metrics(counts: np.ndarray, logits: np.ndarray, mu: np.ndarray, theta: float) -> dict[str, Any]:
    y = counts.astype(np.int64).reshape(-1)
    p = 1.0 / (1.0 + np.exp(-np.clip(logits.reshape(-1), -40, 40)))
    mu = np.maximum(mu.reshape(-1), EPS)
    theta = max(float(theta), EPS)
    positive = y > 0
    p0_log = theta * (np.log(theta) - np.log(theta + mu))
    ppositive = -np.expm1(p0_log)
    positive_mean = mu / np.maximum(ppositive, EPS)
    expected = p * positive_mean
    log_nb = (gammaln(y[positive] + theta) - gammaln(theta) - gammaln(y[positive] + 1)
              + theta * (np.log(theta) - np.log(theta + mu[positive]))
              + y[positive] * (np.log(mu[positive]) - np.log(theta + mu[positive])))
    zt = log_nb - np.log(np.maximum(ppositive[positive], EPS))
    joint = np.empty_like(p)
    joint[positive] = -np.log(np.maximum(p[positive], EPS)) - zt
    joint[~positive] = -np.log(np.maximum(1 - p[~positive], EPS))
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
    result: dict[str, Any] = {
        "joint_hurdle_nll": float(np.mean(joint)),
        "bernoulli_nll": float(log_loss(positive, np.clip(p, EPS, 1 - EPS), labels=[0, 1])),
        "brier": float(brier_score_loss(positive, p)),
        "pr_auc": float(average_precision_score(positive, p)),
        "roc_auc": float(roc_auc_score(positive, p)) if np.unique(positive).size == 2 else None,
        "all_cell_mae": float(np.mean(np.abs(y - expected))),
        "all_cell_rmse": float(np.sqrt(np.mean((y - expected) ** 2))),
        "fitted_theta": theta,
        "mean_predicted_count": float(expected.mean()),
        "mean_observed_count": float(y.mean()),
        "conditional_positive_mean": float(positive_mean[positive].mean()) if positive.any() else None,
    }
    if counts.ndim == 2:
        result.update({
            "weekly_observed_total": counts.sum(axis=1).tolist(),
            "weekly_predicted_total": expected.reshape(counts.shape).sum(axis=1).tolist(),
            "weekly_observed_positive_nodes": (counts > 0).sum(axis=1).tolist(),
            "weekly_predicted_positive_nodes": p.reshape(counts.shape).sum(axis=1).tolist(),
        })
    if positive.any():
        result.update({
            "zt_nb_nll": float(-np.mean(zt)),
            "positive_count_mae": float(np.mean(np.abs(y[positive] - positive_mean[positive]))),
            "positive_count_rmse": float(np.sqrt(np.mean((y[positive] - positive_mean[positive]) ** 2))),
            "positive_mean_observed": float(y[positive].mean()),
            "positive_mean_predicted": float(positive_mean[positive].mean()),
        })
        pos_pred = positive_mean[positive]
        edges = np.unique(np.quantile(pos_pred, np.linspace(0, 1, 6)))
        count_calibration = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            selected = (pos_pred >= lo) & ((pos_pred <= hi) if hi == edges[-1] else (pos_pred < hi))
            if selected.any():
                count_calibration.append({"lower": float(lo), "upper": float(hi), "n": int(selected.sum()), "mean_predicted": float(pos_pred[selected].mean()), "mean_observed": float(y[positive][selected].mean()), "mae": float(np.mean(np.abs(y[positive][selected] - pos_pred[selected]))), "rmse": float(np.sqrt(np.mean((y[positive][selected] - pos_pred[selected]) ** 2)))})
        result["positive_count_calibration"] = count_calibration
    # Calibration is deliberately descriptive; it does not fit or apply a calibrator.
    from sklearn.linear_model import LogisticRegression
    clipped = np.clip(p, EPS, 1 - EPS)
    if np.unique(positive).size == 2:
        cal = LogisticRegression(C=1e6, solver="lbfgs", max_iter=100).fit(np.log(clipped / (1 - clipped)).reshape(-1, 1), positive)
        result["calibration_intercept"] = float(cal.intercept_[0])
        result["calibration_slope"] = float(cal.coef_[0, 0])
    else:
        result["calibration_intercept"] = None; result["calibration_slope"] = None
    quantile_edges = np.unique(np.quantile(p, np.linspace(0, 1, 11)))
    reliability = []
    for lo, hi in zip(quantile_edges[:-1], quantile_edges[1:]):
        selected = (p >= lo) & ((p <= hi) if hi == quantile_edges[-1] else (p < hi))
        if selected.any(): reliability.append({"lower": float(lo), "upper": float(hi), "n": int(selected.sum()), "mean_predicted": float(p[selected].mean()), "observed_fraction": float(positive[selected].mean())})
    result["reliability"] = reliability
    return result


def step_model(model: torch.nn.Module, model_type: str, x: torch.Tensor, edge_index: torch.Tensor, edge_weight: torch.Tensor | None, hidden: torch.Tensor | None) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    if model_type == "gconvgru":
        return model.step(x, edge_index, edge_weight, hidden)
    return model.step(x, hidden)


def train_run(
    data: dict[str, Any], features: np.ndarray, train_mask: np.ndarray, eval_mask: np.ndarray,
    model_type: str, hidden_size: int, k: int, dropout: float, lr: float, seed: int,
    fold: int, regime: str, max_epochs: int, patience: int, chunk: int, device: torch.device,
    output_root: Path, evaluation_mode: str = "development", feature_variant: str = "all", spatial_fold: int | None = None,
    loss_objective: str = "balanced_multitask_loss", positive_loss_multiplier: float = 1.0,
    experiment: str = "task2b",
) -> dict[str, Any]:
    torch.manual_seed(seed); np.random.seed(seed)
    if device.type == "cuda": torch.cuda.manual_seed_all(seed)
    n_nodes, n_features = features.shape[1], features.shape[2]
    model = (GConvGRUHurdleNB(n_features, hidden_size, k, dropout).to(device)
             if model_type == "gconvgru" else GRUHurdleNB(n_features, hidden_size, dropout).to(device))
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    edge_array = data["edges"][["source_node", "target_node"]].to_numpy(np.int64).T.copy()
    edge_index = torch.as_tensor(edge_array, dtype=torch.long, device=device)
    edge_weight = torch.ones(edge_index.shape[1], dtype=torch.float32, device=device) if model_type == "gconvgru" else None
    x = torch.as_tensor(features, dtype=torch.float32, device=device)
    counts = torch.as_tensor(np.asarray(data["counts"]), dtype=torch.float32, device=device)
    train_mask_t = torch.as_tensor(train_mask, dtype=torch.bool, device=device)
    eval_mask_t = torch.as_tensor(eval_mask, dtype=torch.bool, device=device)
    assert_development_only(eval_mask, data, evaluation_mode)
    context = N_CONTEXT
    train_last = context + int(np.max(np.where(train_mask.any(axis=1))[0])) + 1
    eval_indices = np.where(eval_mask.any(axis=1))[0]
    if not len(eval_indices): raise ValueError("evaluation mask is empty")
    eval_last = context + int(np.max(eval_indices)) + 1
    best_score = math.inf; best_epoch = 0; best_state = None; wait = 0
    trajectories = []
    started = time.time()
    clip_count = 0; nonfinite_events = 0
    if loss_objective not in {"balanced_multitask_loss", "exact_joint_hurdle_nll"}:
        raise ValueError(f"unknown loss objective: {loss_objective}")
    if positive_loss_multiplier < 0:
        raise ValueError("positive loss multiplier must be nonnegative")
    for epoch in range(1, max_epochs + 1):
        model.train(); hidden = None; epoch_losses = []
        epoch_components = {"bernoulli_nll": [], "zt_nb_nll": [], "balanced_multitask_loss": [], "exact_joint_hurdle_nll": [], "weighted_bernoulli_contribution": [], "weighted_zt_nb_contribution": []}
        # Environmental context initializes the state but never contributes loss.
        with torch.no_grad():
            for time_index in range(context):
                _, _, _, hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, hidden)
        for start in range(context, train_last, chunk):
            optimizer.zero_grad(set_to_none=True)
            logits_list, mu_list, theta_list = [], [], []
            stop = min(start + chunk, train_last)
            for time_index in range(start, stop):
                logits, mu, theta, hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, hidden)
                logits_list.append(logits); mu_list.append(mu); theta_list.append(theta)
            local = train_mask_t[start - context:stop - context]
            loss_result = None
            for local_index, (logits, mu, theta, mask) in enumerate(zip(logits_list, mu_list, theta_list, local)):
                current = __import__("hurdle_zt_nb").hurdle_losses(
                    logits, mu, model.heads.raw_theta, counts[start - context + local_index], mask,
                    positive_weight=positive_loss_multiplier,
                )
                keys = ["balanced_multitask_loss", "exact_joint_hurdle_nll", "optimization_loss", "bernoulli_nll", "zt_nb_nll", "joint_nll", "positive_count", "weighted_bernoulli_contribution", "weighted_zt_nb_contribution"]
                loss_result = current if loss_result is None else {key: loss_result[key] + current[key] for key in keys}
            if loss_result is None: raise RuntimeError("empty training chunk")
            steps = max(1, stop - start)
            balanced_value = loss_result["balanced_multitask_loss"] / steps
            exact_value = loss_result["exact_joint_hurdle_nll"] / steps
            loss = exact_value if loss_objective == "exact_joint_hurdle_nll" else balanced_value
            if not torch.isfinite(loss): raise FloatingPointError("non-finite training loss")
            loss.backward()
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if not torch.isfinite(grad_norm): raise FloatingPointError("non-finite gradient norm")
            if float(grad_norm) > 1.0: clip_count += 1
            optimizer.step(); epoch_losses.append(float(loss.detach().cpu()))
            for key in epoch_components:
                epoch_components[key].append(float((loss_result[key] / steps).detach().cpu()))
            hidden = hidden.detach()
        # Sequential validation starts from post-training history for future
        # weeks. Spatial evaluation uses the same development weeks as
        # training, so it is replayed from warm-up with current weights.
        model.eval(); pred_logits = []; pred_mu = []; pred_theta = []
        eval_start_time = train_last if train_last < eval_last else context
        validation_hidden = hidden if train_last < eval_last else None
        with torch.no_grad():
            if train_last >= eval_last:
                for time_index in range(context):
                    _, _, _, validation_hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, validation_hidden)
            for time_index in range(eval_start_time, eval_last):
                logits, mu, theta, validation_hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, validation_hidden)
                pred_logits.append(logits.cpu().numpy()); pred_mu.append(mu.cpu().numpy()); pred_theta.append(float(theta.cpu()))
        first_eval = eval_start_time - context
        eval_mask_slice = eval_mask[first_eval:eval_last - context]
        eval_count_slice = np.asarray(data["counts"])[first_eval:eval_last - context]
        metrics = exact_metrics(eval_count_slice[eval_mask_slice], np.asarray(pred_logits)[eval_mask_slice], np.asarray(pred_mu)[eval_mask_slice], float(np.mean(pred_theta)))
        score = metrics["joint_hurdle_nll"]
        trajectories.append({
            "epoch": epoch,
            "loss_objective": loss_objective,
            "positive_loss_multiplier": positive_loss_multiplier,
            "training_optimization_loss": float(np.mean(epoch_losses)),
            "training_balanced_multitask_loss": float(np.mean(epoch_components["balanced_multitask_loss"])),
            "training_exact_joint_hurdle_nll": float(np.mean(epoch_components["exact_joint_hurdle_nll"])),
            "training_bernoulli_nll": float(np.mean(epoch_components["bernoulli_nll"])),
            "training_zt_nb_nll": float(np.mean(epoch_components["zt_nb_nll"])),
            "training_weighted_bernoulli_contribution": float(np.mean(epoch_components["weighted_bernoulli_contribution"])),
            "training_weighted_zt_nb_contribution": float(np.mean(epoch_components["weighted_zt_nb_contribution"])),
            "validation_joint_nll": score,
            "validation_pr_auc": metrics["pr_auc"],
            "theta": float(np.mean(pred_theta)),
        })
        if score < best_score - 1e-5:
            best_score = score; best_epoch = epoch; wait = 0; best_state = copy.deepcopy(model.state_dict())
        else:
            wait += 1
            if wait >= patience: break
    if best_state is None: raise RuntimeError("no valid checkpoint produced")
    model.load_state_dict(best_state)
    elapsed = time.time() - started
    # Re-evaluate the requested mask with the restored model.
    model.eval(); hidden = None; all_logits = []; all_mu = []; theta = None
    with torch.no_grad():
        for time_index in range(context):
            _, _, _, hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, hidden)
        for time_index in range(context, eval_last):
            logits, mu, theta_t, hidden = step_model(model, model_type, x[time_index], edge_index, edge_weight, hidden)
            all_logits.append(logits.cpu().numpy()); all_mu.append(mu.cpu().numpy()); theta = float(theta_t.cpu())
    offset = context
    logits_eval = np.asarray(all_logits)[eval_indices[0]:eval_indices[-1] + 1]
    mu_eval = np.asarray(all_mu)[eval_indices[0]:eval_indices[-1] + 1]
    mask_eval = eval_mask[eval_indices[0]:eval_indices[-1] + 1]
    counts_eval = np.asarray(data["counts"])[eval_indices[0]:eval_indices[-1] + 1]
    final_metrics = exact_metrics(counts_eval[mask_eval], logits_eval[mask_eval], mu_eval[mask_eval], theta)
    spatial_token = "" if spatial_fold is None else f"_spatial{spatial_fold}"
    loss_token = "" if experiment == "task2b" else f"_loss{loss_objective}_lam{positive_loss_multiplier:g}"
    run_id = f"{model_type}_fold{fold}_{regime}{spatial_token}_{feature_variant}_seed{seed}_h{hidden_size}_k{k}_d{dropout:g}_lr{lr:g}{loss_token}"
    run_dir = output_root / f"runs/{experiment}"; model_dir = output_root / f"models/{experiment}"; run_dir.mkdir(parents=True, exist_ok=True); model_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "run_id": run_id, "metrics": final_metrics, "loss_objective": loss_objective, "positive_loss_multiplier": positive_loss_multiplier}, model_dir / f"{run_id}.pt")
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    dataset_manifest_path = data["model_root"] / "manifests/dataset_manifest.json"
    split_manifest_path = data["model_root"] / "splits/temporal_splits.json"
    record = {"run_id": run_id, "experiment": experiment, "model": model_type, "feature_variant": feature_variant, "input_width": n_features, "fold": fold, "regime": regime, "spatial_fold": spatial_fold, "seed": seed, "hidden_size": hidden_size, "K": k, "dropout": dropout, "learning_rate": lr, "loss_objective": loss_objective, "positive_loss_multiplier": positive_loss_multiplier, "chunk_length": chunk, "max_epochs": max_epochs, "best_epoch": best_epoch, "runtime_seconds": elapsed, "gradient_clip_norm": 1.0, "gradient_clip_frequency": clip_count, "nonfinite_gradient_events": nonfinite_events, "git_sha": git_sha, "dataset_manifest_sha256": sha256_file(dataset_manifest_path), "split_manifest_sha256": sha256_file(split_manifest_path), "python": platform.python_version(), "pytorch": torch.__version__, "cuda_available": bool(torch.cuda.is_available()), "cuda_runtime": torch.version.cuda, "gpu_model": torch.cuda.get_device_name(device) if device.type == "cuda" else None, "torch_geometric": __import__("torch_geometric").__version__ if model_type == "gconvgru" else None, "torch_geometric_temporal": __import__("torch_geometric_temporal").__version__ if model_type == "gconvgru" else None, "mixed_precision": False, "metrics": final_metrics, "training_trajectory": trajectories, "final_test_predictive_metrics_calculated": False}
    write_json(run_dir / f"{run_id}.json", record)
    return record


def make_masks(data: dict[str, Any], fold: int, regime: str, spatial_fold: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    n_weeks, n_nodes = data["counts"].shape
    train_indices, valid_indices = split_indices(data, fold)
    train = np.zeros((n_weeks, n_nodes), dtype=bool)
    evaluation = np.zeros_like(train)
    if regime == "temporal":
        train[train_indices, :] = True; evaluation[valid_indices, :] = True
    elif regime == "spatial":
        if spatial_fold is None: raise ValueError("spatial_fold required")
        nodes = data["spatial"]["spatial_fold"].to_numpy() == spatial_fold
        development = np.asarray(data["splits"]["development"]["indices"])
        train[np.ix_(development, ~nodes)] = True
        evaluation[np.ix_(development, nodes)] = True
    elif regime == "combined":
        if spatial_fold is None: raise ValueError("spatial_fold required")
        stem = f"temporal{fold}_spatial{spatial_fold}"
        base = data["model_root"] / "splits/combined_masks"
        train = np.load(base / f"{stem}_train_loss.npy")
        evaluation = np.load(base / f"{stem}_evaluation.npy")
    else: raise ValueError(f"unknown regime {regime}")
    assert_development_only(evaluation, data, "development")
    return train, evaluation


def build_features(data: dict[str, Any], fold: int) -> tuple[np.ndarray, dict[str, Any]]:
    train, _ = split_indices(data, fold)
    prep = fit_preprocessor(data, train)
    return apply_preprocessor(data, prep), prep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fold", type=int, default=1)
    parser.add_argument("--model", choices=["gru", "gconvgru"], default="gconvgru")
    parser.add_argument("--regime", choices=["temporal", "spatial", "combined"], default="temporal")
    parser.add_argument("--spatial-fold", type=int)
    parser.add_argument("--hidden", type=int, default=32)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--chunk", type=int, default=13)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--evaluation-mode", choices=["development", "final"], default="development")
    parser.add_argument("--feature-variant", choices=["all", "without_livestock", "without_calendar"], default="all")
    parser.add_argument("--loss-objective", choices=["balanced_multitask_loss", "exact_joint_hurdle_nll"], default="balanced_multitask_loss")
    parser.add_argument("--positive-loss-multiplier", type=float, default=1.0)
    parser.add_argument("--experiment", default="task2b")
    parser.add_argument("--write-preprocessor", action="store_true")
    args = parser.parse_args()
    if args.evaluation_mode != "development":
        raise RuntimeError("Task 2B execution is development-only; final mode is reserved for Task 2C")
    data = load_data(args.output_root); assert_dataset(data)
    features, prep = build_features(data, args.fold)
    if args.feature_variant == "without_livestock":
        features = np.concatenate([features[:, :, :12], features[:, :, 22:]], axis=2)
    elif args.feature_variant == "without_calendar":
        features = features[:, :, :22]
    if args.write_preprocessor:
        write_json(data["model_root"] / f"scaling/task2b_temporal_fold_{args.fold}.json", prep)
    train_mask, eval_mask = make_masks(data, args.fold, args.regime, args.spatial_fold)
    if not args.cpu and not torch.cuda.is_available(): raise RuntimeError("CUDA is unavailable; use an allocated Atlas GPU node")
    device = torch.device("cpu" if args.cpu else "cuda")
    record = train_run(data, features, train_mask, eval_mask, args.model, args.hidden, args.k, args.dropout, args.lr, args.seed, args.fold, args.regime, args.epochs, args.patience, args.chunk, device, args.output_root, feature_variant=args.feature_variant, spatial_fold=args.spatial_fold, loss_objective=args.loss_objective, positive_loss_multiplier=args.positive_loss_multiplier, experiment=args.experiment)
    print(json.dumps(jsonable(record), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
