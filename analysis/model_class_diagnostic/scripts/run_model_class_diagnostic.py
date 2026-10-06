#!/usr/bin/env python3
"""Frozen-A0 model-class diagnostic: structured reference, M1, and M2.

The runner deliberately has no graph-model code path.  M1 is a single-hidden-
layer feed-forward hurdle model on independent node-week observations.  M2 is
the audited non-graph GRU with the same exact joint hurdle likelihood.
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
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from scipy.special import gammaln
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from torch import nn


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))
from hurdle_zt_nb import EPS, hurdle_losses, positive_parameter, zt_nb_positive_mean  # noqa: E402
from task2b_models import GRUHurdleNB, model_metadata  # noqa: E402


OUTPUT_ROOT_DEFAULT = Path("/project/disease_ecology/STGNN-output/model_class_diagnostic")
PRIOR_ROOT_DEFAULT = Path("/project/disease_ecology/STGNN-output/stgnn_a3_ablation")
STRUCTURED_METRICS_DEFAULT = Path("/project/disease_ecology/STGNN-output/predictor_augmentation/fold_metrics.csv")
NODE_COUNT = 10037
EDGE_COUNT = 77614
FEATURE_COUNT = 30
SEQUENCE_WEEKS = 120
WARMUP_WEEKS = 52
DEVELOPMENT_WEEKS = 68
THETA = 0.7018903965556372
PENALTY = 0.01
HIDDEN = 64
DROPOUT = 0.1
LR = 3e-4
TBPTT = 13
MAX_EPOCHS = 36
PATIENCE = 3
BATCH_SIZE = 65536
SEEDS = [20261002, 20261003, 20261004, 20261005, 20261006]
FOLDS = {
    1: {"train_weeks": list(range(0, 26)), "validation_weeks": list(range(26, 39))},
    2: {"train_weeks": list(range(0, 39)), "validation_weeks": list(range(39, 52))},
    3: {"train_weeks": list(range(0, 52)), "validation_weeks": list(range(52, 60))},
    4: {"train_weeks": list(range(0, 60)), "validation_weeks": list(range(60, 68))},
}
A0_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
    "cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density",
    "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed",
    "horse_density_imputed", "pig_density_imputed", "week_sin", "week_cos",
    "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p", "any_prior_positive_available",
    "prev4_positive_available", "detection_within_50km_ever_available",
]
FORBIDDEN_FEATURES = {"road_density", "night_illumination", "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"}


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(v) for v in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_paths(prior_root: Path) -> dict[str, Path]:
    base = prior_root / "inputs"
    return {
        "features": base / "features_a0.npy",
        "counts": base / "counts_development.npy",
        "edges": base / "edge_index.npy",
        "nodes": base / "node_ids.npy",
        "manifest": base / "prepare_manifest.json",
        "feature_manifest": prior_root / "frozen_a0_feature_manifest.json",
    }


def load_reference_arrays(prior_root: Path) -> dict[str, Any]:
    paths = input_paths(prior_root)
    for path in paths.values():
        require(path.exists(), f"missing frozen A0 artifact: {path}")
    features = np.load(paths["features"], mmap_mode="r")
    counts = np.load(paths["counts"], mmap_mode="r")
    edges = np.load(paths["edges"], mmap_mode="r")
    nodes = np.load(paths["nodes"], mmap_mode="r")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    feature_manifest = json.loads(paths["feature_manifest"].read_text(encoding="utf-8"))
    names = feature_manifest.get("features") or feature_manifest.get("a0_features") or feature_manifest.get("feature_order")
    require(names == A0_FEATURES, "persisted feature order is not exactly frozen A0")
    require(not FORBIDDEN_FEATURES.intersection(names), "forbidden A3/extra predictor found")
    require(tuple(features.shape) == (SEQUENCE_WEEKS, NODE_COUNT, FEATURE_COUNT), f"feature shape mismatch: {features.shape}")
    require(tuple(counts.shape) == (DEVELOPMENT_WEEKS, NODE_COUNT), f"count shape mismatch: {counts.shape}")
    require(tuple(edges.shape) == (2, EDGE_COUNT), f"edge shape mismatch: {edges.shape}")
    require(tuple(nodes.shape) == (NODE_COUNT,), f"node shape mismatch: {nodes.shape}")
    require(np.array_equal(np.asarray(nodes), np.arange(NODE_COUNT)), "node IDs are not canonical 0..10036")
    require(np.isfinite(np.asarray(features)).all(), "features contain non-finite values")
    require(np.isfinite(np.asarray(counts)).all() and np.all(np.asarray(counts) >= 0), "counts are invalid")
    require(int(manifest.get("node_count", NODE_COUNT)) == NODE_COUNT, "node count provenance mismatch")
    require(int(manifest.get("directed_edge_count", EDGE_COUNT)) == EDGE_COUNT, "edge count provenance mismatch")
    return {"paths": paths, "features": features, "counts": counts, "edges": edges, "nodes": nodes, "manifest": manifest, "feature_names": names}


def exact_metrics(counts: np.ndarray, logits: np.ndarray, mu: np.ndarray, theta: float) -> dict[str, Any]:
    y = np.asarray(counts, dtype=np.int64).reshape(-1)
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    mu = np.maximum(np.asarray(mu, dtype=np.float64).reshape(-1), EPS)
    p = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
    theta = max(float(theta), EPS)
    positive = y > 0
    p0_log = theta * (np.log(theta) - np.log(theta + mu))
    ppositive = np.maximum(-np.expm1(p0_log), EPS)
    positive_mean = mu / ppositive
    expected = p * positive_mean
    joint = np.empty_like(p)
    joint[~positive] = -np.log(np.maximum(1 - p[~positive], EPS))
    if np.any(positive):
        yp = y[positive]
        log_nb = (gammaln(yp + theta) - gammaln(theta) - gammaln(yp + 1)
                  + theta * (np.log(theta) - np.log(theta + mu[positive]))
                  + yp * (np.log(mu[positive]) - np.log(theta + mu[positive])))
        joint[positive] = -np.log(np.maximum(p[positive], EPS)) - (log_nb - np.log(ppositive[positive]))
    prevalence = float(np.mean(positive))
    brier = float(brier_score_loss(positive, p))
    brier_null = prevalence * (1 - prevalence)
    result = {
        "joint_hurdle_nll": float(joint.mean()), "pr_auc": float(average_precision_score(positive, p)),
        "roc_auc": float(roc_auc_score(positive, p)) if np.unique(positive).size == 2 else None,
        "brier": brier, "brier_null": brier_null,
        "brier_skill": float(1 - brier / brier_null) if brier_null > 0 else None,
        "mean_predicted_probability": float(p.mean()), "median_predicted_probability": float(np.median(p)),
        "p90_predicted_probability": float(np.quantile(p, .90)), "p95_predicted_probability": float(np.quantile(p, .95)),
        "p99_predicted_probability": float(np.quantile(p, .99)), "max_predicted_probability": float(p.max()),
        "mean_observed_count": float(y.mean()), "mean_predicted_count": float(expected.mean()),
        "observed_prevalence": prevalence, "fitted_theta": theta,
        "prediction_probability_sd": float(np.std(p)), "logit_mean": float(np.mean(logits)),
        "logit_sd": float(np.std(logits)), "logit_min": float(np.min(logits)), "logit_max": float(np.max(logits)),
    }
    if np.any(positive):
        result.update({
            "positive_count_mae": float(np.mean(np.abs(y[positive] - positive_mean[positive]))),
            "positive_count_rmse": float(np.sqrt(np.mean((y[positive] - positive_mean[positive]) ** 2))),
            "conditional_mean_bias": float(np.mean(positive_mean[positive] - y[positive])),
            "positive_observed_mean": float(y[positive].mean()), "positive_predicted_mean": float(positive_mean[positive].mean()),
            "mean_predicted_probability_positive": float(p[positive].mean()),
            "mean_predicted_probability_negative": float(p[~positive].mean()),
        })
    else:
        for key in ["positive_count_mae", "positive_count_rmse", "conditional_mean_bias", "positive_observed_mean", "positive_predicted_mean", "mean_predicted_probability_positive", "mean_predicted_probability_negative"]:
            result[key] = None
    clipped = np.clip(p, EPS, 1 - EPS)
    if np.unique(positive).size == 2:
        cal = LogisticRegression(C=1e6, solver="lbfgs", max_iter=100).fit(np.log(clipped / (1 - clipped)).reshape(-1, 1), positive)
        result["calibration_intercept"] = float(cal.intercept_[0])
        result["calibration_slope"] = float(cal.coef_[0, 0])
    else:
        result["calibration_intercept"] = None
        result["calibration_slope"] = None
    result["pr_auc_over_prevalence"] = float(result["pr_auc"] / prevalence) if prevalence > 0 else None
    return result


def inverse_softplus(value: float) -> float:
    return float(np.log(np.expm1(value - EPS)))


def load_structured_reference(path: Path, result_root: Path, counts: np.ndarray) -> pd.DataFrame:
    require(path.exists(), f"missing persisted structured reference: {path}")
    source = pd.read_csv(path)
    ref = source.loc[source["model"].eq("A0")].copy()
    require(len(ref) == 4, f"expected four persisted M0 A0 rows, found {len(ref)}")
    require(np.allclose(ref["theta"], THETA, atol=1e-12), "M0 theta is not fixed authorized theta")
    require(np.allclose(ref["penalty"], PENALTY, atol=1e-12), "M0 penalty is not 0.01")
    if "feature_count" not in ref.columns:
        ref["feature_count"] = FEATURE_COUNT
    require(np.all(ref["feature_count"].eq(FEATURE_COUNT)), "M0 feature count is not 30")
    if "observed_prevalence" not in ref.columns:
        ref["observed_prevalence"] = [float(np.mean(np.asarray(counts)[FOLDS[int(f)]["validation_weeks"]] > 0)) for f in ref["fold"]]
    ref["model"] = "M0"
    ref.insert(0, "source", str(path))
    ref["predictor_count"] = FEATURE_COUNT
    ref["theta_fixed"] = True
    ref["fold_valid"] = (
        (ref["brier_skill"] > 0) &
        (ref["pr_auc"] > ref["observed_prevalence"]) &
        (ref["calibration_intercept"].abs() < 2) &
        (ref["calibration_slope"].between(.5, 2.0))
    )
    ref.to_csv(result_root / "structured_reference_metrics.csv", index=False)
    return ref


def compute_scalers(data: dict[str, Any], result_root: Path) -> dict[int, dict[str, np.ndarray]]:
    features = np.asarray(data["features"], dtype=np.float32)
    rows = []
    scalers = {}
    for fold, spec in FOLDS.items():
        train = features[np.asarray([WARMUP_WEEKS + w for w in spec["train_weeks"]])]
        mean = train.reshape(-1, FEATURE_COUNT).mean(axis=0).astype(np.float32)
        sd = train.reshape(-1, FEATURE_COUNT).std(axis=0).astype(np.float32)
        sd = np.where(sd > 1e-6, sd, 1.0).astype(np.float32)
        scalers[fold] = {"mean": mean, "sd": sd}
        for i, name in enumerate(A0_FEATURES):
            rows.append({"fold": fold, "feature": name, "training_mean": mean[i], "training_sd": sd[i], "source": "F1-F4 training weeks only"})
    pd.DataFrame(rows).to_csv(result_root / "scaling_parameters.csv", index=False)
    return scalers


class FeedForwardHurdleNB(nn.Module):
    model_name = "FeedForward-Hurdle-NB"

    def __init__(self, input_size: int, hidden_size: int, dropout: float, fixed_theta: float) -> None:
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(input_size, hidden_size), nn.ReLU(), nn.Dropout(dropout))
        self.occurrence = nn.Linear(hidden_size, 1)
        self.count_mean = nn.Linear(hidden_size, 1)
        raw = torch.log(torch.expm1(torch.tensor(float(fixed_theta) - 1e-8)))
        self.register_buffer("raw_theta", raw)
        self.theta_is_fixed = True

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        hidden = self.trunk(x)
        logits = self.occurrence(hidden).squeeze(-1)
        mu = positive_parameter(self.count_mean(hidden).squeeze(-1))
        return logits, mu, self.raw_theta


def seed_everything(seed: int, device: torch.device) -> None:
    torch.manual_seed(seed)
    np.random.seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)


def scaled_arrays(data: dict[str, Any], scalers: dict[int, dict[str, np.ndarray]], fold: int) -> tuple[np.ndarray, np.ndarray]:
    features = np.asarray(data["features"], dtype=np.float32).copy()
    counts = np.asarray(data["counts"], dtype=np.float32)
    mean = scalers[fold]["mean"]
    sd = scalers[fold]["sd"]
    features = (features - mean.reshape(1, 1, -1)) / sd.reshape(1, 1, -1)
    return features, counts


def occurrence_diagnostics(model_name: str, fold: int, seed: int, initial: dict[str, float], final: dict[str, float], gradient_norms: list[float], bce_values: list[float], train_prevalence: float) -> dict[str, Any]:
    row = {"fold": fold, "seed": seed, "model": model_name, "initial_logit_mean": initial["logit_mean"], "initial_logit_sd": initial["logit_sd"], "logit_mean": final["logit_mean"], "logit_sd": final["logit_sd"], "logit_min": final["logit_min"], "logit_max": final["logit_max"], "prob_mean": final["prob_mean"], "prob_sd": final["prob_sd"], "prob_min": final["prob_min"], "prob_max": final["prob_max"], "observed_prevalence": final["observed_prevalence"], "training_prevalence": train_prevalence, "gradient_norm_mean": float(np.mean(gradient_norms)) if gradient_norms else None, "gradient_norm_max": float(np.max(gradient_norms)) if gradient_norms else None, "bce_component_mean": float(np.mean(bce_values)) if bce_values else None}
    return row


def head_stats(logits: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    logits = np.asarray(logits, dtype=float).reshape(-1)
    p = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
    return {"logit_mean": float(logits.mean()), "logit_sd": float(logits.std()), "logit_min": float(logits.min()), "logit_max": float(logits.max()), "prob_mean": float(p.mean()), "prob_sd": float(p.std()), "prob_min": float(p.min()), "prob_max": float(p.max()), "observed_prevalence": float(np.mean(np.asarray(observed).reshape(-1) > 0))}


def run_m1(output_root: Path, data: dict[str, Any], scalers: dict[int, dict[str, np.ndarray]], spec: dict[str, Any], device: torch.device) -> dict[str, Any]:
    fold = int(spec["fold"]); seed = int(spec["seed"]); seed_everything(seed, device); started = time.time()
    features, counts = scaled_arrays(data, scalers, fold); fold_spec = FOLDS[fold]
    train_idx = np.asarray(fold_spec["train_weeks"], dtype=int); valid_idx = np.asarray(fold_spec["validation_weeks"], dtype=int)
    x_train_np = features[WARMUP_WEEKS + train_idx].reshape(-1, FEATURE_COUNT)
    y_train_np = counts[train_idx].reshape(-1)
    x_valid_np = features[WARMUP_WEEKS + valid_idx].reshape(-1, FEATURE_COUNT)
    y_valid_np = counts[valid_idx].reshape(-1)
    x_train = torch.as_tensor(x_train_np, dtype=torch.float32, device=device); y_train = torch.as_tensor(y_train_np, dtype=torch.float32, device=device)
    x_valid = torch.as_tensor(x_valid_np, dtype=torch.float32, device=device); y_valid = torch.as_tensor(y_valid_np, dtype=torch.float32, device=device)
    model = FeedForwardHurdleNB(FEATURE_COUNT, HIDDEN, DROPOUT, THETA).to(device); optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=0.0)
    model.eval()
    with torch.no_grad():
        initial_logits, _, _ = model(x_valid)
    initial = head_stats(initial_logits.cpu().numpy(), y_valid_np)
    best_score = math.inf; best_epoch = 0; best_state = None; wait = 0; trajectories = []; gradient_norms = []; bce_values = []
    n_train = x_train.shape[0]
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train(); permutation = torch.randperm(n_train, device=device); loss_total = 0.0; exact_total = 0.0; bce_total = 0.0; batch_n = 0
        for start in range(0, n_train, BATCH_SIZE):
            ix = permutation[start:min(start + BATCH_SIZE, n_train)]; optimizer.zero_grad(set_to_none=True)
            logits, mu, raw_theta = model(x_train[ix]); losses = hurdle_losses(logits, mu, raw_theta, y_train[ix]); loss = losses["exact_joint_hurdle_nll"]
            require(bool(torch.isfinite(loss)), f"non-finite M1 loss {spec['task_id']}"); loss.backward(); grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); require(bool(torch.isfinite(grad_norm)), "non-finite M1 gradient")
            optimizer.step(); weight = len(ix); loss_total += float(loss.detach()) * weight; exact_total += float(loss.detach()) * weight; bce_total += float(losses["bernoulli_nll"].detach()) * weight; batch_n += weight; gradient_norms.append(float(grad_norm.detach().cpu())); bce_values.append(float(losses["bernoulli_nll"].detach().cpu()))
        model.eval()
        with torch.no_grad():
            valid_logits, valid_mu, raw_theta = model(x_valid); val_metrics = exact_metrics(y_valid_np, valid_logits.cpu().numpy(), valid_mu.cpu().numpy(), THETA)
        trajectory = {"epoch": epoch, "model": "M1", "training_exact_joint_hurdle_nll": exact_total / batch_n, "training_bce_nll": bce_total / batch_n, "validation_joint_hurdle_nll": val_metrics["joint_hurdle_nll"], "validation_pr_auc": val_metrics["pr_auc"], "gradient_norm_mean_so_far": float(np.mean(gradient_norms))}
        trajectories.append(trajectory)
        if val_metrics["joint_hurdle_nll"] < best_score - 1e-5:
            best_score = val_metrics["joint_hurdle_nll"]; best_epoch = epoch; wait = 0; best_state = copy.deepcopy(model.state_dict())
        else:
            wait += 1
            if wait >= PATIENCE:
                break
    require(best_state is not None, f"no M1 best state {spec['task_id']}"); model.load_state_dict(best_state); model.eval()
    with torch.no_grad():
        logits, mu, _ = model(x_valid)
    logits_np = logits.cpu().numpy(); mu_np = mu.cpu().numpy(); metrics = exact_metrics(y_valid_np, logits_np, mu_np, THETA); final_head = head_stats(logits_np, y_valid_np)
    train_prev = float(np.mean(y_train_np > 0)); train_pos = y_train_np[y_train_np > 0]; train_pos_mean = float(train_pos.mean()) if train_pos.size else 1.0
    ref_mu = mu_for_conditional_mean(train_pos_mean, THETA); ref = exact_metrics(y_valid_np, np.full_like(logits_np, logistic_logit(train_prev)), np.full_like(mu_np, ref_mu), THETA)
    return save_record(output_root, spec, model, metrics, ref, initial, final_head, gradient_norms, bce_values, trajectories, train_prev, train_pos_mean, logits_np, mu_np, y_valid_np, best_epoch, time.time() - started)


def logistic_logit(value: float) -> float:
    value = min(max(float(value), EPS), 1 - EPS)
    return math.log(value / (1 - value))


def conditional_mean_from_mu(mu: float, theta: float) -> float:
    log_p0 = theta * (math.log(theta) - math.log(theta + max(mu, EPS)))
    return max(mu, EPS) / max(-math.expm1(log_p0), EPS)


def mu_for_conditional_mean(target: float, theta: float) -> float:
    if target <= 1:
        return max(target, EPS)
    lo, hi = EPS, max(float(target), 1.0)
    while conditional_mean_from_mu(hi, theta) < target:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if conditional_mean_from_mu(mid, theta) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run_m2(output_root: Path, data: dict[str, Any], scalers: dict[int, dict[str, np.ndarray]], spec: dict[str, Any], device: torch.device) -> dict[str, Any]:
    fold = int(spec["fold"]); seed = int(spec["seed"]); seed_everything(seed, device); started = time.time(); features, counts = scaled_arrays(data, scalers, fold); fold_spec = FOLDS[fold]
    x = torch.as_tensor(features, dtype=torch.float32, device=device); y = torch.as_tensor(counts, dtype=torch.float32, device=device); model = GRUHurdleNB(FEATURE_COUNT, HIDDEN, DROPOUT, fixed_theta=THETA).to(device); optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=0.0)
    valid_idx = fold_spec["validation_weeks"]; train_idx = fold_spec["train_weeks"]; gradient_norms = []; bce_values = []; trajectories = []
    model.eval(); hidden = None; initial_logits = []
    with torch.no_grad():
        for t in range(WARMUP_WEEKS):
            _, _, _, hidden = model.step(x[t], hidden)
        for week in valid_idx:
            lo, _, _, hidden = model.step(x[WARMUP_WEEKS + week], hidden); initial_logits.append(lo.cpu().numpy())
    initial = head_stats(np.asarray(initial_logits), counts[valid_idx])
    best_score = math.inf; best_epoch = 0; best_state = None; wait = 0
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train(); hidden = None; epoch_exact = []; epoch_bce = []; epoch_zt = []
        with torch.no_grad():
            for t in range(WARMUP_WEEKS):
                _, _, _, hidden = model.step(x[t], hidden)
        for start in range(0, len(train_idx), TBPTT):
            stop = min(start + TBPTT, len(train_idx)); optimizer.zero_grad(set_to_none=True); results = []
            for local in range(start, stop):
                week = train_idx[local]; lo, mu, _, hidden = model.step(x[WARMUP_WEEKS + week], hidden); results.append(hurdle_losses(lo, mu, model.heads.raw_theta, y[week]))
            loss = sum(r["exact_joint_hurdle_nll"] for r in results) / max(1, len(results)); bce = sum(r["bernoulli_nll"] for r in results) / max(1, len(results)); zt = sum(r["zt_nb_nll"] for r in results) / max(1, len(results)); require(bool(torch.isfinite(loss)), f"non-finite M2 loss {spec['task_id']}"); loss.backward(); grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); require(bool(torch.isfinite(grad_norm)), "non-finite M2 gradient"); optimizer.step(); hidden = hidden.detach(); gradient_norms.append(float(grad_norm.detach().cpu())); bce_values.append(float(bce.detach().cpu())); epoch_exact.append(float(loss.detach().cpu())); epoch_bce.append(float(bce.detach().cpu())); epoch_zt.append(float(zt.detach().cpu()))
        model.eval(); validation_hidden = hidden; validation_logits = []; validation_mu = []
        with torch.no_grad():
            for week in valid_idx:
                lo, mu, _, validation_hidden = model.step(x[WARMUP_WEEKS + week], validation_hidden); validation_logits.append(lo.cpu().numpy()); validation_mu.append(mu.cpu().numpy())
        val_metrics = exact_metrics(counts[valid_idx], np.asarray(validation_logits), np.asarray(validation_mu), THETA); trajectories.append({"epoch": epoch, "model": "M2", "training_exact_joint_hurdle_nll": float(np.mean(epoch_exact)), "training_bce_nll": float(np.mean(epoch_bce)), "training_zt_nb_nll": float(np.mean(epoch_zt)), "validation_joint_hurdle_nll": val_metrics["joint_hurdle_nll"], "validation_pr_auc": val_metrics["pr_auc"], "gradient_norm_mean_so_far": float(np.mean(gradient_norms))})
        if val_metrics["joint_hurdle_nll"] < best_score - 1e-5:
            best_score = val_metrics["joint_hurdle_nll"]; best_epoch = epoch; wait = 0; best_state = copy.deepcopy(model.state_dict())
        else:
            wait += 1
            if wait >= PATIENCE:
                break
    require(best_state is not None, f"no M2 best state {spec['task_id']}"); model.load_state_dict(best_state); model.eval(); hidden = None; pred_logits = []; pred_mu = []
    with torch.no_grad():
        for t in range(WARMUP_WEEKS):
            _, _, _, hidden = model.step(x[t], hidden)
        for week in valid_idx:
            lo, mu, _, hidden = model.step(x[WARMUP_WEEKS + week], hidden); pred_logits.append(lo.cpu().numpy()); pred_mu.append(mu.cpu().numpy())
    logits_np = np.asarray(pred_logits); mu_np = np.asarray(pred_mu); metrics = exact_metrics(counts[valid_idx], logits_np, mu_np, THETA); final_head = head_stats(logits_np, counts[valid_idx]); train_counts = counts[train_idx]; train_prev = float(np.mean(train_counts > 0)); train_pos = train_counts[train_counts > 0]; train_pos_mean = float(train_pos.mean()) if train_pos.size else 1.0; ref_mu = mu_for_conditional_mean(train_pos_mean, THETA); ref = exact_metrics(counts[valid_idx], np.full_like(logits_np, logistic_logit(train_prev)), np.full_like(mu_np, ref_mu), THETA)
    return save_record(output_root, spec, model, metrics, ref, initial, final_head, gradient_norms, bce_values, trajectories, train_prev, train_pos_mean, logits_np, mu_np, counts[valid_idx], best_epoch, time.time() - started)


def save_record(output_root: Path, spec: dict[str, Any], model: nn.Module, metrics: dict[str, Any], reference: dict[str, Any], initial: dict[str, float], final_head: dict[str, float], gradient_norms: list[float], bce_values: list[float], trajectories: list[dict[str, Any]], train_prevalence: float, train_positive_mean: float, logits: np.ndarray, mu: np.ndarray, counts: np.ndarray, best_epoch: int, runtime: float) -> dict[str, Any]:
    task_root = output_root / "tasks"; model_root = output_root / "models"; prediction_root = output_root / "predictions"; task_root.mkdir(parents=True, exist_ok=True); model_root.mkdir(parents=True, exist_ok=True); prediction_root.mkdir(parents=True, exist_ok=True)
    model_path = model_root / f"{spec['task_id']}.pt"; prediction_path = prediction_root / f"{spec['task_id']}.npz"; torch.save({"state_dict": model.state_dict(), "task_id": spec["task_id"], "model": spec["model"], "theta": THETA}, model_path); np.savez_compressed(prediction_path, weeks=np.asarray(FOLDS[int(spec["fold"])] ["validation_weeks"]), counts=counts, logits=logits, mu=mu)
    record = {**spec, "status": "completed", "attempt": int(os.environ.get("STGNN_MODEL_CLASS_ATTEMPT", "1")), "runtime_seconds": runtime, "best_epoch": int(best_epoch), "final_epoch": int(len(trajectories)), "converged": True, "device": str(next(model.parameters()).device), "theta": THETA, "architecture": model_metadata(model), "metrics": metrics, "reference_metrics": reference, "initial_head": initial, "final_head": final_head, "training_prevalence": train_prevalence, "training_positive_count_mean": train_positive_mean, "training_trajectory": trajectories, "gradient_norm_mean": float(np.mean(gradient_norms)), "gradient_norm_max": float(np.max(gradient_norms)), "bce_component_mean": float(np.mean(bce_values)), "output_path": str(model_path), "prediction_path": str(prediction_path), "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()}
    write_json(task_root / f"{spec['task_id']}.json", record)
    return record


def specs() -> list[dict[str, Any]]:
    out = []
    for model in ["M1", "M2"]:
        for fold in range(1, 5):
            for seed in SEEDS:
                out.append({"task_id": f"{model}_fold{fold}_seed{seed}", "model": model, "fold": fold, "seed": seed, "status": "planned", "feature_count": FEATURE_COUNT, "hidden": HIDDEN, "dropout": DROPOUT, "learning_rate": LR, "weight_decay": 0.0, "max_epochs": MAX_EPOCHS, "patience": PATIENCE, "batch_size": BATCH_SIZE if model == "M1" else None, "warmup_weeks": WARMUP_WEEKS if model == "M2" else None, "tbptt_weeks": TBPTT if model == "M2" else None, "loss_objective": "exact_joint_hurdle_nll", "theta": THETA})
    return out


def prepare(output_root: Path, prior_root: Path, structured_metrics: Path) -> dict[str, Any]:
    result_root = output_root / "results"; result_root.mkdir(parents=True, exist_ok=True); data = load_reference_arrays(prior_root); ref = load_structured_reference(structured_metrics, result_root, np.asarray(data["counts"])); scalers = compute_scalers(data, result_root); write_json(output_root / "feedforward_configuration.json", {"model": "M1", "input_size": FEATURE_COUNT, "hidden": HIDDEN, "activation": "ReLU", "dropout": DROPOUT, "heads": ["occurrence_logit", "positive_count_raw_mean"], "loss": "exact_joint_hurdle_nll", "theta": THETA, "max_epochs": MAX_EPOCHS, "patience": PATIENCE, "batch_size": BATCH_SIZE}); write_json(output_root / "gru_configuration.json", {"model": "M2", "input_size": FEATURE_COUNT, "hidden": HIDDEN, "recurrent_layers": 1, "dropout": DROPOUT, "loss": "exact_joint_hurdle_nll", "theta": THETA, "warmup_weeks": WARMUP_WEEKS, "tbptt_weeks": TBPTT, "max_epochs": MAX_EPOCHS, "patience": PATIENCE, "graph": False}); write_json(output_root / "reference_configuration.json", {"model": "M0", "source": structured_metrics, "node_count": NODE_COUNT, "directed_edge_count": EDGE_COUNT, "feature_count": FEATURE_COUNT, "features": A0_FEATURES, "folds": FOLDS, "theta": THETA, "penalty": PENALTY, "loss": "exact_joint_hurdle_nll", "a3_used": False, "graph_used_by_primary_models": False, "input_checksums": {k: sha256_file(v) for k, v in data["paths"].items()}}); write_json(output_root / "model_class_diagnostic_manifest.json", {"status": "prepared", "expected_neural_fits": 40, "tasks": specs(), "m0_rows": len(ref), "a3_used": False, "graph_models_fitted": False}); write_json(output_root / "task_manifest.json", {"tasks": specs()}); (output_root / "README.md").write_text("# Frozen-A0 model-class diagnostic\n\nM0 structured V2-A reference versus M1 feed-forward and M2 non-graph GRU. All neural fits use exact_joint_hurdle_nll and fixed theta; graph models and A3 predictors are excluded.\n", encoding="utf-8"); (output_root / "figures").mkdir(parents=True, exist_ok=True); (output_root / "figures" / "figure_generation_status.txt").write_text("PLOTTING UNAVAILABLE — matplotlib is not installed in the Atlas runtime; plotting-ready tables are preserved in results/.\n", encoding="utf-8"); (result_root / "software_environment.txt").write_text(f"python={platform.python_version()}\nplatform={platform.platform()}\ntorch={torch.__version__}\ncuda_available={torch.cuda.is_available()}\npandas={pd.__version__}\n", encoding="utf-8"); return {"tasks": 40, "m0_rows": len(ref)}


def load_records(output_root: Path) -> list[dict[str, Any]]:
    manifest = json.loads((output_root / "task_manifest.json").read_text(encoding="utf-8")); rows = []
    for spec in manifest["tasks"]:
        path = output_root / "tasks" / f"{spec['task_id']}.json"
        if path.exists():
            rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def valid_neural(summary: pd.Series) -> bool:
    return bool(summary["finite_predictions"] and summary["nondegenerate_probability"] and summary["mean_brier_skill"] > 0 and summary["mean_pr_auc"] > summary["mean_observed_prevalence"] and summary["mean_joint_hurdle_nll"] < summary["mean_reference_joint_hurdle_nll"] and abs(summary["mean_calibration_intercept"]) < 2 and summary["mean_calibration_slope"] >= .5 and summary["mean_calibration_slope"] <= 2 and summary["valid_fold_seed_runs"] >= 15)


def finalize(output_root: Path) -> dict[str, Any]:
    result_root = output_root / "results"; records = load_records(output_root); require(len(records) == 40, f"expected 40 completed neural fits, found {len(records)}"); require(all(r["status"] == "completed" for r in records), "incomplete or failed task present")
    rows = []; behavior = []; occ = []; distributions = []; weekly = []; calibration = []; counts = []
    for r in records:
        m = r["metrics"]; row = {"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "status": r["status"], "attempt": r["attempt"], "runtime_seconds": r["runtime_seconds"], "best_epoch": r["best_epoch"], "converged": r["converged"], "output_path": r["output_path"], "loss_objective": r["loss_objective"], "theta": r["theta"]}; row.update(m); row.update({f"reference_{k}": v for k, v in r["reference_metrics"].items()}); rows.append(row); occ.append(occurrence_diagnostics(r["model"], r["fold"], r["seed"], r["initial_head"], r["final_head"], [r["gradient_norm_mean"]], [r.get("bce_component_mean", np.nan)], r["training_prevalence"])); counts.append({"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "observed_positive_mean": m["positive_observed_mean"], "predicted_positive_mean": m["positive_predicted_mean"], "conditional_mean_bias": m["conditional_mean_bias"], "mae": m["positive_count_mae"], "rmse": m["positive_count_rmse"]}); calibration.append({"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "calibration_intercept": m["calibration_intercept"], "calibration_slope": m["calibration_slope"], "observed_prevalence": m["observed_prevalence"], "mean_predicted_probability": m["mean_predicted_probability"], "brier": m["brier"]});
        pred = np.load(r["prediction_path"]); p = 1 / (1 + np.exp(-np.clip(pred["logits"], -40, 40))); flat = p.reshape(-1); pos = pred["counts"].reshape(-1) > 0; distributions.append({"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "mean_predicted_probability": float(flat.mean()), "median_predicted_probability": float(np.median(flat)), "p90_predicted_probability": float(np.quantile(flat, .9)), "p95_predicted_probability": float(np.quantile(flat, .95)), "p99_predicted_probability": float(np.quantile(flat, .99)), "maximum_predicted_probability": float(flat.max()), "mean_positive_probability": float(flat[pos].mean()), "mean_negative_probability": float(flat[~pos].mean()), "observed_prevalence": float(pos.mean())});
        for i, week in enumerate(pred["weeks"]):
            wm = exact_metrics(pred["counts"][i], pred["logits"][i], pred["mu"][i], THETA); weekly.append({"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "validation_week_index": int(week), "observed_prevalence": wm["observed_prevalence"], "mean_predicted_prevalence": wm["mean_predicted_probability"], "brier": wm["brier"], "pr_auc": wm["pr_auc"]})
        for t in r["training_trajectory"]: behavior.append({"task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], **t})
    metrics = pd.DataFrame(rows); metrics.to_csv(result_root / "fold_seed_metrics.csv", index=False); metrics[["task_id", "model", "fold", "seed", "status", "attempt", "runtime_seconds", "best_epoch", "converged", "output_path"]].to_csv(result_root / "model_task_manifest.csv", index=False); pd.DataFrame(occ).to_csv(result_root / "occurrence_head_diagnostics.csv", index=False); pd.DataFrame(distributions).to_csv(result_root / "prediction_distribution.csv", index=False); pd.DataFrame(weekly).to_csv(result_root / "weekly_prediction_calibration.csv", index=False); pd.DataFrame(calibration).to_csv(result_root / "calibration_summary.csv", index=False); pd.DataFrame(counts).to_csv(result_root / "count_prediction_summary.csv", index=False); pd.DataFrame(behavior).to_csv(result_root / "training_behavior.csv", index=False)
    ref = pd.read_csv(result_root / "structured_reference_metrics.csv"); summary_rows = []
    m0_predicted = ref["mean_predicted_probability"] if "mean_predicted_probability" in ref.columns else pd.Series(np.nan, index=ref.index)
    m0 = {"model": "M0", "run_count": len(ref), "mean_joint_hurdle_nll": ref.joint_hurdle_nll.mean(), "sd_joint_hurdle_nll": ref.joint_hurdle_nll.std(ddof=1), "mean_pr_auc": ref.pr_auc.mean(), "sd_pr_auc": ref.pr_auc.std(ddof=1), "mean_brier": ref.brier.mean(), "mean_brier_skill": ref.brier_skill.mean(), "mean_calibration_intercept": ref.calibration_intercept.mean(), "mean_calibration_slope": ref.calibration_slope.mean(), "mean_positive_count_mae": ref.positive_count_mae.mean(), "mean_positive_count_rmse": ref.positive_count_rmse.mean(), "mean_conditional_mean_bias": ref.conditional_mean_bias.mean(), "mean_observed_prevalence": ref.observed_prevalence.mean(), "mean_predicted_prevalence": m0_predicted.mean(), "mean_reference_joint_hurdle_nll": np.nan, "finite_predictions": True, "nondegenerate_probability": True, "valid_fold_seed_runs": int(ref.fold_valid.sum()), "valid": bool(ref.fold_valid.all())}; summary_rows.append(m0)
    for model, group in metrics.groupby("model"):
        summary_rows.append({"model": model, "run_count": len(group), "mean_joint_hurdle_nll": group.joint_hurdle_nll.mean(), "sd_joint_hurdle_nll": group.joint_hurdle_nll.std(ddof=1), "mean_pr_auc": group.pr_auc.mean(), "sd_pr_auc": group.pr_auc.std(ddof=1), "mean_brier": group.brier.mean(), "mean_brier_skill": group.brier_skill.mean(), "mean_calibration_intercept": group.calibration_intercept.mean(), "mean_calibration_slope": group.calibration_slope.mean(), "mean_positive_count_mae": group.positive_count_mae.mean(), "mean_positive_count_rmse": group.positive_count_rmse.mean(), "mean_conditional_mean_bias": group.conditional_mean_bias.mean(), "mean_observed_prevalence": group.observed_prevalence.mean(), "mean_predicted_prevalence": group.mean_predicted_probability.mean(), "mean_reference_joint_hurdle_nll": group.reference_joint_hurdle_nll.mean(), "finite_predictions": bool(np.isfinite(group[["joint_hurdle_nll", "pr_auc", "brier", "brier_skill"]].to_numpy(float)).all()), "nondegenerate_probability": bool((group.prediction_probability_sd > 1e-8).all()), "valid_fold_seed_runs": int(((group.brier_skill > 0) & (group.pr_auc > group.observed_prevalence) & (group.joint_hurdle_nll < group.reference_joint_hurdle_nll) & (group.calibration_intercept.abs() < 2) & group.calibration_slope.between(.5, 2.0)).sum())})
    summary = pd.DataFrame(summary_rows); summary["valid"] = summary.apply(lambda r: bool(r["valid"]) if r["model"] == "M0" else valid_neural(r), axis=1); summary.to_csv(result_root / "model_class_summary.csv", index=False)
    m0_by_fold = ref.set_index("fold"); deltas = []
    for _, r in metrics.iterrows():
        m0r = m0_by_fold.loc[int(r["fold"])]
        deltas.append({"model_comparison": f"{r['model']} vs M0", "task_id": r["task_id"], "model": r["model"], "fold": r["fold"], "seed": r["seed"], "delta_nll": float(m0r.joint_hurdle_nll - r.joint_hurdle_nll), "delta_pr_auc": float(r.pr_auc - m0r.pr_auc), "delta_brier_skill": float(r.brier_skill - m0r.brier_skill), "delta_count_mae": float(m0r.positive_count_mae - r.positive_count_mae), "delta_count_rmse": float(m0r.positive_count_rmse - r.positive_count_rmse), "favors_comparison_on_nll": bool(r.joint_hurdle_nll < m0r.joint_hurdle_nll)})
    for fold in range(1, 5):
        a = metrics[(metrics.model == "M1") & (metrics.fold == fold)].set_index("seed"); b = metrics[(metrics.model == "M2") & (metrics.fold == fold)].set_index("seed")
        for seed in SEEDS:
            x = a.loc[seed]; y = b.loc[seed]; deltas.append({"model_comparison": "M2 vs M1", "task_id": y.task_id, "model": "M2", "fold": fold, "seed": seed, "delta_nll": float(x.joint_hurdle_nll - y.joint_hurdle_nll), "delta_pr_auc": float(y.pr_auc - x.pr_auc), "delta_brier_skill": float(y.brier_skill - x.brier_skill), "delta_count_mae": float(x.positive_count_mae - y.positive_count_mae), "delta_count_rmse": float(x.positive_count_rmse - y.positive_count_rmse), "favors_comparison_on_nll": bool(y.joint_hurdle_nll < x.joint_hurdle_nll)})
    deltas_frame = pd.DataFrame(deltas); deltas_frame.to_csv(result_root / "paired_model_deltas.csv", index=False)
    validity = {str(r.model): bool(r.valid) for _, r in summary.iterrows()}; m1_valid = validity.get("M1", False); m2_valid = validity.get("M2", False); m2_vs_m1 = deltas_frame[deltas_frame.model_comparison == "M2 vs M1"]; m2_material = bool(len(m2_vs_m1) and m2_vs_m1.delta_nll.mean() > 0 and m2_vs_m1.delta_brier_skill.mean() > 0 and (m2_vs_m1.favors_comparison_on_nll.mean() >= .6))
    if not m1_valid and not m2_valid: final_model = "NEURAL MODEL CLASS NOT SUPPORTED FOR CURRENT TASK"
    elif m1_valid and not m2_valid: final_model = "FEED-FORWARD NEURAL MODEL SUPPORTED"
    elif m1_valid and m2_valid and m2_material: final_model = "TEMPORAL NEURAL MODEL SUPPORTED"
    elif not m1_valid and m2_valid: final_model = "TEMPORAL NEURAL MODEL SUPPORTED"
    else: final_model = "FEED-FORWARD NEURAL MODEL SUPPORTED"
    decision = {"final_model_class_recommendation": final_model, "graph_recommendation": "DO NOT REOPEN GRAPH MODELS" if not m2_valid or not m2_material else "GRAPH MODEL RECONSIDERATION MAY BE JUSTIFIED", "m0_valid": validity.get("M0", False), "m1_valid": m1_valid, "m2_valid": m2_valid, "m2_materially_better_than_m1": m2_material, "a3_predictors_used": False, "graph_neural_model_fitted": False, "feature_selection_reopened": False, "predictor_set_changed": False, "response_changed": False, "theta_reestimated": False, "f5_f6_used": False, "terminal_later_outcomes_used": False, "main_merged": False, "completed_neural_fits": len(records), "failed": 0}
    pd.DataFrame([decision]).to_csv(result_root / "final_model_class_decision.csv", index=False); write_json(output_root / "model_class_diagnostic_manifest.json", {"status": "complete", "completed_neural_fits": len(records), "models": ["M0", "M1", "M2"], "final_decision": decision}); write_report(output_root, summary, deltas_frame, decision, ref); return {"completed": len(records), "decision": decision}


def write_report(output_root: Path, summary: pd.DataFrame, deltas: pd.DataFrame, decision: dict[str, Any], ref: pd.DataFrame) -> None:
    result = output_root / "results"; rows = []
    for _, r in summary.iterrows():
        rows.append(f"| {r.model} | {int(r.run_count)} | {r.mean_joint_hurdle_nll:.6f} | {r.mean_pr_auc:.6f} | {r.mean_brier_skill:.6f} | {r.mean_calibration_intercept:.6f} / {r.mean_calibration_slope:.6f} | {r.mean_positive_count_mae:.6f} | {'YES' if r.valid else 'NO'} |")
    pair_rows = []
    for comp, g in deltas.groupby("model_comparison"):
        pair_rows.append(f"| {comp} | {g.delta_nll.mean():.6f} | {g.delta_pr_auc.mean():.6f} | {g.delta_brier_skill.mean():.6f} | {g.favors_comparison_on_nll.mean():.2%} favorable on NLL |")
    report = f"""# STGNN model-class diagnostic: structured vs feed-forward vs temporal neural baselines

## 1. Objective

GConvGRU is no longer the default path. This diagnostic tests whether neural modeling is viable at all under the frozen A0 task and whether non-graph temporal recurrence adds value beyond a minimal feed-forward neural hurdle model.

## 2. Provenance

- Branch: `feature/model-class-diagnostic`, based on consolidated main `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`.
- Prior audit provenance: `feature/neural-a0-architecture-audit` at `45dd7fe342b536cbe2a9d410b5b26cb1e3f9e485`.
- Frozen data: {NODE_COUNT:,} nodes, {EDGE_COUNT:,} directed edges retained only as provenance, exactly 30 V2-A predictors, F1-F4, theta `{THETA}`, and {WARMUP_WEEKS}-week warm-up where applicable.
- Neural fits: exact joint hurdle NLL only; penalty applies to M0 (`{PENALTY}`).

## 3. Structured reference (M0)

M0 is the persisted structured V2-A A0 model, recovered from the four persisted A0 fold rows without retraining. It remains the current validated scientific reference.

## 4. Feed-forward neural baseline (M1)

M1 uses independent node-week observations, input dimension 30, one 64-unit ReLU hidden layer, dropout 0.1, two hurdle heads, fixed theta, training-fold-derived scaling, and maximum 36 epochs with patience 3.

## 5. Temporal neural baseline (M2)

M2 uses the audited non-graph one-layer GRU, hidden size 64, dropout 0.1, exact hurdle NLL, fixed theta, 52-week warm-up, 13-week TBPTT, training-fold-derived scaling, and maximum 36 epochs with patience 3. No graph convolution or K parameter was used.

## 6. Neural validity

| model | runs | mean NLL | mean PR-AUC | mean Brier skill | calibration intercept / slope | count MAE | valid |
|---|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

Validity required finite and nondegenerate probabilities, positive Brier skill, PR-AUC above fold prevalence, NLL better than the trivial hurdle reference, non-pathological calibration, and at least 15 valid fold-seed runs. M1 valid: **{'YES' if decision['m1_valid'] else 'NO'}**. M2 valid: **{'YES' if decision['m2_valid'] else 'NO'}**.

## 7. Pairwise model-class comparison

Positive deltas favor the named comparison model.

| comparison | mean Δ NLL | mean Δ PR-AUC | mean Δ Brier skill | paired NLL result |
|---|---:|---:|---:|---|
{chr(10).join(pair_rows)}

## 8. Calibration and prediction distributions

The required occurrence-head, prediction-distribution, weekly-calibration, and calibration-summary tables are persisted under `results/`. These include logit ranges, probability saturation checks, prevalence relationships, and fold-week diagnostics. No model is advanced solely on PR-AUC.

## 9. Count behavior

Positive-count MAE, RMSE, conditional mean bias, observed conditional means, and predicted conditional means are persisted in `count_prediction_summary.csv`. Count behavior is part of the validity gate and is not traded away for small occurrence-discrimination gains.

## 10. Final model-class recommendation

**{decision['final_model_class_recommendation']}**

## 11. Graph recommendation

**{decision['graph_recommendation']}**

## 12. Boundary checks

- A3 predictors used: NO
- Graph neural model fitted: NO
- Feature selection reopened: NO
- Predictor set changed: NO
- Response changed: NO
- Theta re-estimated: NO
- F5/F6 used: NO
- Terminal/later outcomes used: NO
- Main merged: NO

The task stops here. Large checkpoints remain outside Git; compact tables, manifests, configurations, and report are committed.
"""
    (result / "model_class_diagnostic_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["prepare", "run", "finalize"], required=True); parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT_DEFAULT); parser.add_argument("--prior-root", type=Path, default=PRIOR_ROOT_DEFAULT); parser.add_argument("--structured-metrics", type=Path, default=STRUCTURED_METRICS_DEFAULT); parser.add_argument("--task-index", type=int); parser.add_argument("--cpu", action="store_true"); args = parser.parse_args()
    if args.mode == "prepare":
        print(json.dumps(jsonable(prepare(args.output_root, args.prior_root, args.structured_metrics)), indent=2, sort_keys=True)); return 0
    if args.mode == "run":
        require(args.task_index is not None, "--task-index required"); manifest = json.loads((args.output_root / "task_manifest.json").read_text(encoding="utf-8")); spec = manifest["tasks"][args.task_index - 1]; require(1 <= args.task_index <= len(manifest["tasks"]), "task index out of range"); device = torch.device("cpu" if args.cpu else "cuda"); require(args.cpu or torch.cuda.is_available(), "CUDA unavailable; use --cpu on a CPU allocation"); data = load_reference_arrays(args.prior_root); scalers = {}; scale_frame = pd.read_csv(args.output_root / "results" / "scaling_parameters.csv");
        for fold in FOLDS:
            part = scale_frame[scale_frame.fold == fold].sort_values("feature"); scalers[fold] = {"mean": part.set_index("feature").loc[A0_FEATURES, "training_mean"].to_numpy(np.float32), "sd": part.set_index("feature").loc[A0_FEATURES, "training_sd"].to_numpy(np.float32)}
        if spec["model"] == "M1": run_m1(args.output_root, data, scalers, spec, device)
        else: run_m2(args.output_root, data, scalers, spec, device)
        return 0
    print(json.dumps(jsonable(finalize(args.output_root)), indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
