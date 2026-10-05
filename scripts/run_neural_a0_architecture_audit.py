#!/usr/bin/env python3
"""A0-only revised-domain neural architecture/training audit.

The audit deliberately consumes the frozen A0 tensor artifact produced by the
completed revised-domain experiment.  It never loads the A3 tensor.  The
script is restartable: prepare creates the deterministic audits and task
manifest; run executes one task; extend appends a bounded diagnostic phase;
finalize aggregates completed task records.
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
from scipy import sparse
from scipy.special import gammaln
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))
from hurdle_zt_nb import EPS, hurdle_losses, positive_parameter, zt_nb_positive_mean  # noqa: E402
from task2b_models import GConvGRUHurdleNB, GRUHurdleNB, model_metadata  # noqa: E402


OUTPUT_ROOT_DEFAULT = Path("/project/disease_ecology/STGNN-output/neural_a0_architecture_audit")
PRIOR_ROOT_DEFAULT = Path("/project/disease_ecology/STGNN-output/stgnn_a3_ablation")
NODE_COUNT = 10037
EDGE_COUNT = 77614
FEATURE_COUNT = 30
SEQUENCE_WEEKS = 120
WARMUP_WEEKS = 52
DEVELOPMENT_WEEKS = 68
THETA = 0.7018903965556372
HIDDEN = 64
DROPOUT = 0.1
LR = 3e-4
TBPTT = 13
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def input_paths(prior_root: Path) -> dict[str, Path]:
    base = prior_root / "inputs"
    return {
        "features": base / "features_a0.npy",
        "counts": base / "counts_development.npy",
        "edges": base / "edge_index.npy",
        "nodes": base / "node_ids.npy",
        "manifest": base / "prepare_manifest.json",
        "feature_manifest": prior_root / "frozen_a0_feature_manifest.json",
        "graph_qa": prior_root / "graph_qa.csv",
        "tensor_qa": prior_root / "input_tensor_qa.csv",
    }


def load_reference_arrays(prior_root: Path) -> dict[str, Any]:
    paths = input_paths(prior_root)
    for path in paths.values():
        require(path.exists(), f"missing prior A0 artifact: {path}")
    features = np.load(paths["features"], mmap_mode="r")
    counts = np.load(paths["counts"], mmap_mode="r")
    edges = np.load(paths["edges"], mmap_mode="r")
    nodes = np.load(paths["nodes"], mmap_mode="r")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    feature_manifest = json.loads(paths["feature_manifest"].read_text(encoding="utf-8"))
    feature_names = feature_manifest.get("features") or feature_manifest.get("a0_features") or feature_manifest.get("feature_order")
    require(feature_names == A0_FEATURES, "persisted A0 feature order differs from frozen specification")
    require(tuple(features.shape) == (SEQUENCE_WEEKS, NODE_COUNT, FEATURE_COUNT), f"A0 tensor shape mismatch: {features.shape}")
    require(tuple(counts.shape) == (DEVELOPMENT_WEEKS, NODE_COUNT), f"count shape mismatch: {counts.shape}")
    require(tuple(edges.shape) == (2, EDGE_COUNT), f"edge shape mismatch: {edges.shape}")
    require(tuple(nodes.shape) == (NODE_COUNT,), f"node-id shape mismatch: {nodes.shape}")
    require(np.array_equal(np.asarray(nodes), np.arange(NODE_COUNT)), "node order is not canonical 0..10036")
    require(np.isfinite(np.asarray(features)).all(), "A0 tensor contains non-finite values")
    require(np.isfinite(np.asarray(counts)).all() and np.all(np.asarray(counts) >= 0), "counts are invalid")
    require(int(manifest.get("node_count", NODE_COUNT)) == NODE_COUNT, "prior manifest node count mismatch")
    require(int(manifest.get("directed_edge_count", EDGE_COUNT)) == EDGE_COUNT, "prior manifest edge count mismatch")
    return {"paths": paths, "features": features, "counts": counts, "edges": edges, "nodes": nodes, "manifest": manifest, "feature_names": feature_names}


def inverse_softplus(value: float) -> float:
    return float(np.log(np.expm1(value - EPS)))


def exact_single(y: int, p: float, mu: float, theta: float) -> float:
    p = float(np.clip(p, EPS, 1 - EPS))
    mu = max(float(mu), EPS)
    theta = max(float(theta), EPS)
    log_p0 = theta * (math.log(theta) - math.log(theta + mu))
    p_positive = max(-math.expm1(log_p0), EPS)
    if y == 0:
        return -math.log1p(-p)
    log_nb = (gammaln(y + theta) - gammaln(theta) - gammaln(y + 1)
              + theta * (math.log(theta) - math.log(theta + mu))
              + y * (math.log(mu) - math.log(theta + mu)))
    return -math.log(p) - (log_nb - math.log(p_positive))


def loss_component_audit(result_root: Path) -> dict[str, Any]:
    p, mu, theta = 0.2, 2.5, THETA
    logit = torch.tensor(math.log(p / (1 - p)), dtype=torch.float64)
    mu_t = torch.tensor([mu], dtype=torch.float64)
    raw_theta = torch.tensor([inverse_softplus(theta)], dtype=torch.float64)
    cases = [("zero", 0), ("one", 1), ("two", 2), ("large_positive", 100)]
    rows = []
    for name, y_value in cases:
        y = torch.tensor([float(y_value)], dtype=torch.float64)
        current = float(hurdle_losses(logit.reshape(1), mu_t, raw_theta, y)["balanced_multitask_loss"])
        exact = float(hurdle_losses(logit.reshape(1), mu_t, raw_theta, y)["exact_joint_hurdle_nll"])
        rows.append({"case": name, "y": y_value, "p_occurrence": p, "mu": mu, "theta": theta,
                     "structured_exact_nll": exact_single(y_value, p, mu, theta),
                     "neural_current_loss": current, "difference": current - exact_single(y_value, p, mu, theta),
                     "reason": "single-observation terms are algebraically identical"})
    for name, values in [("mixed_batch", [0, 1, 2, 100]), ("rare_positive_batch", [0, 0, 0, 0, 1])]:
        y = torch.tensor(values, dtype=torch.float64)
        logits = torch.full_like(y, math.log(p / (1 - p)))
        mus = torch.full_like(y, mu)
        current_result = hurdle_losses(logits, mus, raw_theta, y)
        current = float(current_result["balanced_multitask_loss"])
        exact = float(current_result["exact_joint_hurdle_nll"])
        rows.append({"case": name, "y": ",".join(map(str, values)), "p_occurrence": p, "mu": mu, "theta": theta,
                     "structured_exact_nll": exact, "neural_current_loss": current, "difference": current - exact,
                     "reason": "positive-count denominator differs from observation-level denominator"})
    frame = pd.DataFrame(rows)
    frame.to_csv(result_root / "loss_component_audit.csv", index=False)
    return {"single_case_max_abs_difference": float(np.max(np.abs(frame.iloc[:4]["difference"]))),
            "mixed_batch_difference": float(frame.loc[frame.case == "mixed_batch", "difference"].iloc[0]),
            "rare_positive_batch_difference": float(frame.loc[frame.case == "rare_positive_batch", "difference"].iloc[0])}


def loss_gradient_audit(result_root: Path) -> dict[str, Any]:
    rows = []
    for name, values in [("mixed_batch", [0, 1, 2, 100]), ("rare_positive_batch", [0, 0, 0, 0, 1]), ("balanced_batch", [0, 1, 0, 2])]:
        y = torch.tensor(values, dtype=torch.float64)
        raw_logit = torch.tensor([math.log(0.2 / 0.8)] * len(values), dtype=torch.float64, requires_grad=True)
        raw_count = torch.tensor([inverse_softplus(2.5)] * len(values), dtype=torch.float64, requires_grad=True)
        raw_theta = torch.tensor([inverse_softplus(THETA)], dtype=torch.float64)
        mu = positive_parameter(raw_count)
        losses = hurdle_losses(raw_logit, mu, raw_theta, y)
        grad_current = torch.autograd.grad(losses["balanced_multitask_loss"], (raw_logit, raw_count), retain_graph=True)
        grad_exact = torch.autograd.grad(losses["exact_joint_hurdle_nll"], (raw_logit, raw_count))
        vec_current = torch.cat([grad_current[0].reshape(-1), grad_current[1].reshape(-1)])
        vec_exact = torch.cat([grad_exact[0].reshape(-1), grad_exact[1].reshape(-1)])
        cosine = float(torch.nn.functional.cosine_similarity(vec_current, vec_exact, dim=0))
        rows.append({"case": name, "n": len(values), "positive_fraction": float(np.mean(np.asarray(values) > 0)),
                     "current_loss": float(losses["balanced_multitask_loss"]), "exact_loss": float(losses["exact_joint_hurdle_nll"]),
                     "loss_difference": float(losses["balanced_multitask_loss"] - losses["exact_joint_hurdle_nll"]),
                     "current_occurrence_gradient_mean": float(grad_current[0].mean()), "exact_occurrence_gradient_mean": float(grad_exact[0].mean()),
                     "current_count_raw_gradient_mean": float(grad_current[1].mean()), "exact_count_raw_gradient_mean": float(grad_exact[1].mean()),
                     "gradient_l2_difference": float(torch.linalg.vector_norm(vec_current - vec_exact)), "gradient_cosine": cosine,
                     "direction_agrees": bool(cosine > 0.99)})
    frame = pd.DataFrame(rows)
    frame.to_csv(result_root / "loss_gradient_audit.csv", index=False)
    return {"max_gradient_l2_difference": float(frame.gradient_l2_difference.max()), "minimum_gradient_cosine": float(frame.gradient_cosine.min())}


def graph_architecture_audit(data: dict[str, Any], result_root: Path) -> dict[str, Any]:
    edges = np.asarray(data["edges"], dtype=np.int64).T
    require(np.all((edges >= 0) & (edges < NODE_COUNT)), "graph edge index out of range")
    pairs = {(int(a), int(b)) for a, b in edges}
    reverse_missing = sum((b, a) not in pairs for a, b in pairs)
    duplicate_count = int(len(edges) - len(pairs))
    self_loops = int(np.sum(edges[:, 0] == edges[:, 1]))
    degree = np.bincount(edges.reshape(-1), minlength=NODE_COUNT)
    undirected = np.vstack([edges, edges[:, ::-1]])
    matrix = sparse.csr_matrix((np.ones(len(undirected)), (undirected[:, 0], undirected[:, 1])), shape=(NODE_COUNT, NODE_COUNT))
    n_components, labels = sparse.csgraph.connected_components(matrix, directed=False, return_labels=True)
    isolate_count = int(np.sum(degree == 0))
    rows = [{"node_count": NODE_COUNT, "directed_edge_count": len(edges), "undirected_edge_count": len(pairs) // 2,
             "connected_components": int(n_components), "isolates": isolate_count, "reverse_edge_missing_count": reverse_missing,
             "duplicate_directed_edges": duplicate_count, "self_loops": self_loops, "node_index_min": int(edges.min()),
             "node_index_max": int(edges.max()), "symmetry_passed": reverse_missing == 0, "expected_components": 4,
             "expected_isolates": 3, "passed": bool(len(edges) == EDGE_COUNT and n_components == 4 and isolate_count == 3 and reverse_missing == 0 and duplicate_count == 0 and self_loops == 0)}]
    pd.DataFrame(rows).to_csv(result_root / "graph_architecture_audit.csv", index=False)
    return rows[0]


def state_audits(result_root: Path) -> None:
    (result_root / "tbptt_state_audit.md").write_text("""# TBPTT state audit\n\n- The audit training loop initializes `hidden = None` at each epoch and runs all 52 warm-up feature weeks under `torch.no_grad()` before response loss begins.\n- Training uses contiguous 13-week chunks. Each chunk calls `optimizer.zero_grad(set_to_none=True)`, performs one optimizer step after the chunk, and detaches the resulting hidden state before the next chunk.\n- Validation follows the final training hidden state when validation is temporally after training; the restored-best-checkpoint final evaluation instead resets hidden and replays the 52-week warm-up before validation.\n- A new model and hidden state are created per fold/seed task, so hidden state is not retained across folds or unrelated tasks.\n- No response loss is calculated during warm-up. Development validation uses only F1--F4 weeks; terminal/later responses are not loaded.\n\nThese references correspond to `scripts/run_neural_a0_architecture_audit.py` and the unchanged recurrent model interfaces in `python/task2b_models.py`.\n""", encoding="utf-8")
    (result_root / "warmup_audit.md").write_text("""# Warm-up audit\n\nThe prepared A0 tensor has 120 weeks: 52 warm-up weeks followed by the 68 development weeks. Every task replays exactly the first 52 feature weeks before training and before final validation prediction. Warm-up weeks do not contribute response loss. Fold training and validation indices are restricted to the four specified development splits; no F5/F6 or terminal/later outcomes are loaded.\n\nThe input artifact is the persisted A0 tensor from the completed revised-domain experiment, verified at shape `[120, 10037, 30]`, with canonical node order and 77,614 directed edges.\n""", encoding="utf-8")


def build_reference_configuration(output_root: Path, prior_root: Path, data: dict[str, Any], loss_summary: dict[str, Any], gradient_summary: dict[str, Any], graph_summary: dict[str, Any]) -> dict[str, Any]:
    config = {
        "audit_version": "neural-a0-architecture-audit-v1",
        "source_previous_branch": "feature/stgnn-a3-ablation",
        "source_previous_sha": "4797edff54c019cdd978b92e57413b58992d18ec",
        "input_source_root": prior_root,
        "input_source_sha256": {key: sha256_file(path) for key, path in data["paths"].items() if path.suffix in {".npy", ".json"}},
        "node_count": NODE_COUNT, "directed_edge_count": EDGE_COUNT, "feature_count": FEATURE_COUNT,
        "a0_features": A0_FEATURES, "a3_used": False, "response_changed": False,
        "folds": FOLDS, "warmup_weeks": WARMUP_WEEKS, "tbptt_weeks": TBPTT,
        "theta": THETA, "seeds": SEEDS,
        "reference_architecture": {"model": "GConvGRU-Hurdle-NB", "hidden_dimension": HIDDEN, "K": 3, "normalization": "sym", "recurrent_layers": 1, "dropout": DROPOUT, "optimizer": "Adam", "learning_rate": LR, "weight_decay": 0.0, "gradient_clip_norm": 1.0, "epoch_limit": 12, "early_stopping_patience": 3, "loss": "balanced_multitask_loss", "positive_loss_multiplier": 1.0},
        "loss_audit": loss_summary, "gradient_audit": gradient_summary, "graph_audit": graph_summary,
        "terminal_response_loaded": False, "feature_selection_reopened": False,
    }
    write_json(output_root / "reference_configuration.json", config)
    return config


def task_specs_for_phase(phase: str, loss_objective: str = "balanced_multitask_loss", epochs: int = 12) -> list[dict[str, Any]]:
    if phase == "n1":
        models = [("N1-R", "gconvgru", 3, "balanced_multitask_loss"), ("N1-E", "gconvgru", 3, "exact_joint_hurdle_nll")]
    elif phase == "n2":
        models = [("N2-R", "gconvgru", 3, loss_objective), ("N2-G0", "gru", 0, loss_objective)]
    elif phase == "n3":
        models = [("N3-K1", "gconvgru", 1, loss_objective), ("N3-K3", "gconvgru", 3, loss_objective)]
    elif phase == "n4":
        models = [("N4-E12", "gconvgru", 3, loss_objective), ("N4-E36", "gconvgru", 3, loss_objective)]
    else:
        raise ValueError(phase)
    specs = []
    for model_id, model_type, k, objective in models:
        for fold in range(1, 5):
            for seed in SEEDS:
                specs.append({"task_id": f"{model_id}_fold{fold}_seed{seed}", "audit_phase": phase.upper(), "model_id": model_id,
                              "model_type": model_type, "fold": fold, "seed": seed, "k": k, "loss_objective": objective,
                              "hidden": HIDDEN, "dropout": DROPOUT, "learning_rate": LR, "weight_decay": 0.0,
                              "warmup_weeks": WARMUP_WEEKS, "tbptt_weeks": TBPTT, "max_epochs": epochs, "patience": 3,
                              "theta": THETA, "status": "planned"})
    return specs


def prepare(output_root: Path, prior_root: Path) -> dict[str, Any]:
    result_root = output_root / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    data = load_reference_arrays(prior_root)
    loss_summary = loss_component_audit(result_root)
    gradient_summary = loss_gradient_audit(result_root)
    graph_summary = graph_architecture_audit(data, result_root)
    state_audits(result_root)
    config = build_reference_configuration(output_root, prior_root, data, loss_summary, gradient_summary, graph_summary)
    specs = task_specs_for_phase("n1")
    write_json(output_root / "audit_task_manifest.json", {"phase": "N1", "tasks": specs, "completed": 0, "failed": 0})
    (output_root / "figures").mkdir(parents=True, exist_ok=True)
    (output_root / "figures" / "figure_generation_status.txt").write_text("PLOTTING TABLES AVAILABLE; FIGURE GENERATION DEFERRED UNTIL FINAL AGGREGATION\n", encoding="utf-8")
    (output_root / "README.md").write_text("# Revised-domain neural A0 architecture/training audit\n\nA0-only, F1-F4, five paired seeds. A3 predictors and terminal outcomes are excluded. Large arrays and checkpoints remain under Atlas output storage.\n", encoding="utf-8")
    return {"output_root": output_root, "reference_configuration": config, "task_count": len(specs), "loss_summary": loss_summary, "gradient_summary": gradient_summary, "graph_summary": graph_summary}


def load_audit_data(output_root: Path) -> dict[str, Any]:
    config = json.loads((output_root / "reference_configuration.json").read_text(encoding="utf-8"))
    prior_root = Path(config["input_source_root"])
    return load_reference_arrays(prior_root)


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
    if np.any(positive):
        yp = y[positive]
        log_nb = (gammaln(yp + theta) - gammaln(theta) - gammaln(yp + 1)
                  + theta * (np.log(theta) - np.log(theta + mu[positive]))
                  + yp * (np.log(mu[positive]) - np.log(theta + mu[positive])))
        joint[positive] = -np.log(np.maximum(p[positive], EPS)) - (log_nb - np.log(ppositive[positive]))
    joint[~positive] = -np.log(np.maximum(1 - p[~positive], EPS))
    prevalence = float(np.mean(positive))
    brier = float(brier_score_loss(positive, p))
    baseline_brier = prevalence * (1 - prevalence)
    result = {"joint_hurdle_nll": float(joint.mean()), "pr_auc": float(average_precision_score(positive, p)),
              "roc_auc": float(roc_auc_score(positive, p)) if np.unique(positive).size == 2 else None,
              "brier": brier, "brier_skill": float(1 - brier / baseline_brier) if baseline_brier > 0 else None,
              "mean_predicted_probability": float(p.mean()), "median_predicted_probability": float(np.median(p)),
              "p90_predicted_probability": float(np.quantile(p, .90)), "p95_predicted_probability": float(np.quantile(p, .95)),
              "p99_predicted_probability": float(np.quantile(p, .99)), "max_predicted_probability": float(p.max()),
              "mean_predicted_count": float(expected.mean()), "mean_observed_count": float(y.mean()),
              "observed_prevalence": prevalence, "fitted_theta": theta,
              "prediction_positive_mean_sd": float(np.std(positive_mean)), "prediction_probability_sd": float(np.std(p))}
    if np.any(positive):
        result.update({"positive_count_mae": float(np.mean(np.abs(y[positive] - positive_mean[positive]))),
                       "positive_count_rmse": float(np.sqrt(np.mean((y[positive] - positive_mean[positive]) ** 2))),
                       "positive_count_bias": float(np.mean(positive_mean[positive] - y[positive])),
                       "positive_observed_mean": float(y[positive].mean()), "positive_predicted_mean": float(positive_mean[positive].mean()),
                       "positive_predicted_p50": float(np.quantile(positive_mean[positive], .5)),
                       "positive_predicted_p90": float(np.quantile(positive_mean[positive], .9)),
                       "positive_predicted_p99": float(np.quantile(positive_mean[positive], .99))})
        log_nb = (gammaln(y[positive] + theta) - gammaln(theta) - gammaln(y[positive] + 1)
                  + theta * (np.log(theta) - np.log(theta + mu[positive]))
                  + y[positive] * (np.log(mu[positive]) - np.log(theta + mu[positive])))
        result["zt_nb_nll"] = float(-np.mean(log_nb - np.log(ppositive[positive])))
    else:
        for key in ["positive_count_mae", "positive_count_rmse", "positive_count_bias", "positive_observed_mean", "positive_predicted_mean", "positive_predicted_p50", "positive_predicted_p90", "positive_predicted_p99", "zt_nb_nll"]:
            result[key] = None
    clipped = np.clip(p, EPS, 1 - EPS)
    if np.unique(positive).size == 2:
        cal = LogisticRegression(C=1e6, solver="lbfgs", max_iter=100).fit(np.log(clipped / (1 - clipped)).reshape(-1, 1), positive)
        result["calibration_intercept"] = float(cal.intercept_[0]); result["calibration_slope"] = float(cal.coef_[0, 0])
    else:
        result["calibration_intercept"] = None; result["calibration_slope"] = None
    return result


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


def model_for_spec(spec: dict[str, Any], device: torch.device) -> torch.nn.Module:
    if spec["model_type"] == "gru":
        return GRUHurdleNB(FEATURE_COUNT, HIDDEN, DROPOUT, fixed_theta=THETA).to(device)
    return GConvGRUHurdleNB(FEATURE_COUNT, HIDDEN, int(spec["k"]), DROPOUT, normalization="sym", fixed_theta=THETA).to(device)


def step_model(model: torch.nn.Module, model_type: str, x: torch.Tensor, edge_index: torch.Tensor, edge_weight: torch.Tensor, hidden: torch.Tensor | None):
    if model_type == "gru":
        return model.step(x, hidden)
    return model.step(x, edge_index, edge_weight=edge_weight, hidden=hidden)


def train_task(output_root: Path, spec: dict[str, Any], cpu: bool = False) -> dict[str, Any]:
    data = load_audit_data(output_root)
    features = data["features"]
    counts_np = np.asarray(data["counts"], dtype=np.float32)
    device = torch.device("cpu" if cpu else "cuda")
    if not cpu:
        require(torch.cuda.is_available(), "CUDA unavailable; use an allocated Atlas GPU node or --cpu")
    seed = int(spec["seed"]); torch.manual_seed(seed); np.random.seed(seed)
    if device.type == "cuda": torch.cuda.manual_seed_all(seed)
    model = model_for_spec(spec, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=0.0)
    x = torch.as_tensor(features, dtype=torch.float32, device=device)
    y = torch.as_tensor(counts_np, dtype=torch.float32, device=device)
    edge_index = torch.as_tensor(np.asarray(data["edges"], dtype=np.int64), dtype=torch.long, device=device)
    edge_weight = torch.ones(edge_index.shape[1], dtype=torch.float32, device=device)
    fold = FOLDS[int(spec["fold"])]
    train_weeks = fold["train_weeks"]; valid_weeks = fold["validation_weeks"]
    best_score = math.inf; best_epoch = 0; best_state = None; wait = 0; trajectories = []
    clip_count = 0; nonfinite_events = 0; started = time.time()
    for epoch in range(1, int(spec["max_epochs"]) + 1):
        model.train(); hidden = None; epoch_losses = []; epoch_balanced = []; epoch_exact = []; epoch_bce = []; epoch_zt = []
        with torch.no_grad():
            for time_index in range(WARMUP_WEEKS):
                _, _, _, hidden = step_model(model, spec["model_type"], x[time_index], edge_index, edge_weight, hidden)
        for start in range(0, len(train_weeks), TBPTT):
            stop = min(start + TBPTT, len(train_weeks)); optimizer.zero_grad(set_to_none=True)
            chunk_results = []
            for local in range(start, stop):
                week = train_weeks[local]; logits, mu, theta, hidden = step_model(model, spec["model_type"], x[WARMUP_WEEKS + week], edge_index, edge_weight, hidden)
                chunk_results.append(hurdle_losses(logits, mu, model.heads.raw_theta, y[week], positive_weight=1.0))
            steps = max(1, stop - start)
            keys = ["balanced_multitask_loss", "exact_joint_hurdle_nll", "bernoulli_nll", "zt_nb_nll"]
            sums = {key: sum(result[key] for result in chunk_results) / steps for key in keys}
            loss = sums[spec["loss_objective"]]
            require(bool(torch.isfinite(loss)), f"non-finite training loss in {spec['task_id']}")
            loss.backward(); grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if not torch.isfinite(grad_norm):
                nonfinite_events += 1; raise FloatingPointError("non-finite gradient norm")
            if float(grad_norm) > 1.0: clip_count += 1
            optimizer.step(); hidden = hidden.detach(); epoch_losses.append(float(loss.detach().cpu()))
            epoch_balanced.append(float(sums["balanced_multitask_loss"].detach().cpu())); epoch_exact.append(float(sums["exact_joint_hurdle_nll"].detach().cpu()))
            epoch_bce.append(float(sums["bernoulli_nll"].detach().cpu())); epoch_zt.append(float(sums["zt_nb_nll"].detach().cpu()))
        model.eval(); validation_logits = []; validation_mu = []; validation_theta = []
        with torch.no_grad():
            validation_hidden = hidden
            for week in valid_weeks:
                logits, mu, theta, validation_hidden = step_model(model, spec["model_type"], x[WARMUP_WEEKS + week], edge_index, edge_weight, validation_hidden)
                validation_logits.append(logits.cpu().numpy()); validation_mu.append(mu.cpu().numpy()); validation_theta.append(float(theta.cpu()))
        val_metrics = exact_metrics(counts_np[valid_weeks], np.asarray(validation_logits), np.asarray(validation_mu), float(np.mean(validation_theta)))
        trajectories.append({"epoch": epoch, "loss_objective": spec["loss_objective"], "training_optimization_loss": float(np.mean(epoch_losses)),
                             "training_balanced_multitask_loss": float(np.mean(epoch_balanced)), "training_exact_joint_hurdle_nll": float(np.mean(epoch_exact)),
                             "training_bernoulli_nll": float(np.mean(epoch_bce)), "training_zt_nb_nll": float(np.mean(epoch_zt)),
                             "validation_joint_hurdle_nll": val_metrics["joint_hurdle_nll"], "validation_pr_auc": val_metrics["pr_auc"], "theta": THETA})
        if val_metrics["joint_hurdle_nll"] < best_score - 1e-5:
            best_score = val_metrics["joint_hurdle_nll"]; best_epoch = epoch; wait = 0; best_state = copy.deepcopy(model.state_dict())
        else:
            wait += 1
            if wait >= 3: break
    require(best_state is not None, "no best state produced")
    model.load_state_dict(best_state); model.eval(); pred_logits = []; pred_mu = []; pred_theta = []
    with torch.no_grad():
        hidden = None
        for time_index in range(WARMUP_WEEKS):
            _, _, _, hidden = step_model(model, spec["model_type"], x[time_index], edge_index, edge_weight, hidden)
        for week in valid_weeks:
            logits, mu, theta, hidden = step_model(model, spec["model_type"], x[WARMUP_WEEKS + week], edge_index, edge_weight, hidden)
            pred_logits.append(logits.cpu().numpy()); pred_mu.append(mu.cpu().numpy()); pred_theta.append(float(theta.cpu()))
    theta_value = float(np.mean(pred_theta)); metrics = exact_metrics(counts_np[valid_weeks], np.asarray(pred_logits), np.asarray(pred_mu), theta_value)
    train_counts = counts_np[train_weeks]
    train_positive = train_counts[train_counts > 0]
    train_prevalence = float(np.mean(train_counts > 0))
    train_positive_mean = float(train_positive.mean()) if train_positive.size else 1.0
    reference_mu = mu_for_conditional_mean(train_positive_mean, THETA)
    reference_counts = counts_np[valid_weeks]
    reference_metrics = exact_metrics(reference_counts, np.full(reference_counts.shape, logistic_logit(train_prevalence)), np.full(reference_counts.shape, reference_mu), THETA)
    task_root = output_root / "tasks"; model_root = output_root / "models"; prediction_root = output_root / "predictions"; task_root.mkdir(parents=True, exist_ok=True); model_root.mkdir(parents=True, exist_ok=True); prediction_root.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "task_id": spec["task_id"], "model_id": spec["model_id"], "theta": theta_value}, model_root / f"{spec['task_id']}.pt")
    np.savez_compressed(prediction_root / f"{spec['task_id']}.npz", weeks=np.asarray(valid_weeks), counts=counts_np[valid_weeks], logits=np.asarray(pred_logits), mu=np.asarray(pred_mu))
    metadata = model_metadata(model)
    record = {**spec, "status": "completed", "attempt": int(os.environ.get("STGNN_AUDIT_ATTEMPT", "1")), "runtime_seconds": time.time() - started,
              "best_epoch": best_epoch, "converged": True, "device": str(device), "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
              "slurm_array_task_id": os.environ.get("SLURM_ARRAY_TASK_ID"), "architecture": metadata, "theta": theta_value,
              "metrics": metrics, "reference_metrics": reference_metrics, "training_prevalence": train_prevalence, "training_positive_count_mean": train_positive_mean,
              "training_trajectory": trajectories, "gradient_clip_frequency": clip_count, "nonfinite_gradient_events": nonfinite_events,
              "output_path": str(model_root / f"{spec['task_id']}.pt"), "prediction_path": str(prediction_root / f"{spec['task_id']}.npz"),
              "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(), "final_test_predictive_metrics_calculated": False}
    write_json(task_root / f"{spec['task_id']}.json", record)
    return record


def load_task_manifest(output_root: Path) -> dict[str, Any]:
    path = output_root / "audit_task_manifest.json"
    require(path.exists(), f"missing {path}; prepare first")
    return json.loads(path.read_text(encoding="utf-8"))


def run_one(output_root: Path, task_index: int, cpu: bool = False, force: bool = False) -> dict[str, Any]:
    manifest = load_task_manifest(output_root); specs = manifest["tasks"]
    require(1 <= task_index <= len(specs), f"task index out of range: {task_index}")
    spec = specs[task_index - 1]; path = output_root / "tasks" / f"{spec['task_id']}.json"
    if path.exists() and not force:
        record = json.loads(path.read_text(encoding="utf-8")); print(json.dumps(record, indent=2, sort_keys=True)); return record
    try:
        record = train_task(output_root, spec, cpu=cpu)
    except Exception as exc:
        record = {**spec, "status": "failed", "attempt": int(os.environ.get("STGNN_AUDIT_ATTEMPT", "1")), "error": repr(exc), "converged": False, "slurm_job_id": os.environ.get("SLURM_JOB_ID")}
        write_json(path, record); raise
    print(json.dumps(record, indent=2, sort_keys=True)); return record


def extend(output_root: Path, phase: str, loss_objective: str) -> dict[str, Any]:
    manifest = load_task_manifest(output_root); existing = manifest["tasks"]
    new_specs = task_specs_for_phase(phase, loss_objective=loss_objective, epochs=36 if phase == "n4" else 12)
    existing_ids = {item["task_id"] for item in existing}; additions = [item for item in new_specs if item["task_id"] not in existing_ids]
    manifest["tasks"] = existing + additions; manifest["phase"] = phase.upper(); write_json(output_root / "audit_task_manifest.json", manifest)
    return {"phase": phase.upper(), "added": len(additions), "total": len(manifest["tasks"]), "loss_objective": loss_objective}


def summarize_records(output_root: Path) -> list[dict[str, Any]]:
    manifest = load_task_manifest(output_root); records = []
    for spec in manifest["tasks"]:
        path = output_root / "tasks" / f"{spec['task_id']}.json"
        if path.exists(): records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def valid_gate(summary: pd.Series) -> bool:
    return bool(summary["finite_predictions"] and summary["nondegenerate_probability"] and summary["mean_brier_skill"] > 0 and summary["mean_pr_auc"] > summary["mean_reference_pr_auc"] and summary["mean_joint_hurdle_nll"] < summary["mean_reference_joint_hurdle_nll"])


def finalize(output_root: Path) -> dict[str, Any]:
    result_root = output_root / "results"; result_root.mkdir(parents=True, exist_ok=True)
    records = summarize_records(output_root); require(records, "no completed audit task records")
    require(all(record.get("status") == "completed" for record in records), "cannot finalize with failed/incomplete tasks")
    rows = []
    behavior = []
    runtime = []
    for record in records:
        metrics = record["metrics"]
        row = {"task_id": record["task_id"], "audit_phase": record["audit_phase"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "status": record["status"], "output_path": record["output_path"], "attempt": record["attempt"], "runtime_seconds": record["runtime_seconds"], "best_epoch": record["best_epoch"], "converged": record["converged"], "device": record["device"], "loss_objective": record["loss_objective"], "k": record["k"], "theta": record["theta"]}
        for key, value in metrics.items(): row[key] = value
        for key, value in record.get("reference_metrics", {}).items(): row[f"reference_{key}"] = value
        rows.append(row)
        runtime.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "runtime_seconds": record["runtime_seconds"], "device": record["device"], "best_epoch": record["best_epoch"], "gradient_clip_frequency": record["gradient_clip_frequency"], "nonfinite_gradient_events": record["nonfinite_gradient_events"]})
        for trajectory in record["training_trajectory"]: behavior.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], **trajectory})
    metrics_frame = pd.DataFrame(rows); metrics_frame.to_csv(result_root / "fold_seed_metrics.csv", index=False)
    manifest_frame = metrics_frame[["task_id", "audit_phase", "model_id", "fold", "seed", "status", "output_path", "attempt", "runtime_seconds", "best_epoch", "converged"]]; manifest_frame.to_csv(result_root / "model_task_manifest.csv", index=False)
    pd.DataFrame(runtime).to_csv(result_root / "runtime_resource_comparison.csv", index=False); pd.DataFrame(behavior).to_csv(result_root / "training_behavior.csv", index=False)
    paired_rows = []
    if {"N1-R", "N1-E"}.issubset(set(metrics_frame.model_id)):
        pivot = metrics_frame[metrics_frame.model_id.isin(["N1-R", "N1-E"])].pivot(index=["fold", "seed"], columns="model_id")
        for index, pair in pivot.iterrows():
            row = {"fold": index[0], "seed": index[1]}
            for metric, higher in [("joint_hurdle_nll", False), ("pr_auc", True), ("brier_skill", True), ("brier", False), ("calibration_intercept", False), ("calibration_slope", False), ("positive_count_mae", False), ("positive_count_rmse", False)]:
                r = pair.xs("N1-R", level=1).get(metric); e = pair.xs("N1-E", level=1).get(metric)
                row[f"N1_R_{metric}"] = r; row[f"N1_E_{metric}"] = e
                if r is not None and e is not None and np.isfinite(r) and np.isfinite(e): row[f"delta_{metric}"] = float(e - r if higher else r - e)
            paired_rows.append(row)
    paired = pd.DataFrame(paired_rows); paired.to_csv(result_root / "paired_diagnostic_deltas.csv", index=False)
    summary_rows = []
    for model_id, subset in metrics_frame.groupby("model_id"):
        summary_rows.append({"model_id": model_id, "run_count": len(subset), "mean_joint_hurdle_nll": subset.joint_hurdle_nll.mean(), "sd_joint_hurdle_nll": subset.joint_hurdle_nll.std(ddof=1), "mean_pr_auc": subset.pr_auc.mean(), "sd_pr_auc": subset.pr_auc.std(ddof=1), "mean_brier": subset.brier.mean(), "mean_brier_skill": subset.brier_skill.mean(), "mean_calibration_intercept": subset.calibration_intercept.mean(), "mean_calibration_slope": subset.calibration_slope.mean(), "mean_positive_count_mae": subset.positive_count_mae.mean(), "mean_positive_count_rmse": subset.positive_count_rmse.mean(), "median_runtime_seconds": subset.runtime_seconds.median(), "mean_best_epoch": subset.best_epoch.mean(), "mean_reference_joint_hurdle_nll": subset.reference_joint_hurdle_nll.mean() if "reference_joint_hurdle_nll" in subset else np.nan, "mean_reference_pr_auc": subset.reference_pr_auc.mean() if "reference_pr_auc" in subset else np.nan, "finite_predictions": bool(np.isfinite(subset[["joint_hurdle_nll", "pr_auc", "brier", "brier_skill"]].to_numpy(float)).all()), "nondegenerate_probability": bool((subset.prediction_probability_sd > 1e-8).all())})
    summary = pd.DataFrame(summary_rows); summary.to_csv(result_root / "diagnostic_model_summary.csv", index=False)
    distribution_rows = []; weekly_rows = []; count_rows = []; calibration_rows = []
    for record in records:
        pred = np.load(record["prediction_path"]); weeks = pred["weeks"]; counts = pred["counts"]; logits = pred["logits"]; mu = pred["mu"]; theta = record["theta"]
        p = 1 / (1 + np.exp(-np.clip(logits, -40, 40))); positive = counts > 0; p0 = theta * (np.log(theta) - np.log(theta + np.maximum(mu, EPS))); pos_mean = np.maximum(mu, EPS) / np.maximum(-np.expm1(p0), EPS)
        for index, week in enumerate(weeks):
            week_metrics = exact_metrics(counts[index], logits[index], mu[index], theta)
            weekly_rows.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "validation_week_index": int(week), "observed_prevalence": week_metrics["observed_prevalence"], "mean_predicted_probability": week_metrics["mean_predicted_probability"], "brier": week_metrics["brier"], "pr_auc": week_metrics["pr_auc"]})
        flat_p = p.reshape(-1); flat_positive = positive.reshape(-1); flat_pos_mean = pos_mean.reshape(-1); distribution_rows.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "mean_predicted_probability": float(flat_p.mean()), "median_predicted_probability": float(np.median(flat_p)), "p90_predicted_probability": float(np.quantile(flat_p, .9)), "p95_predicted_probability": float(np.quantile(flat_p, .95)), "p99_predicted_probability": float(np.quantile(flat_p, .99)), "maximum_predicted_probability": float(flat_p.max()), "mean_positive_probability": float(flat_p[flat_positive].mean()), "mean_negative_probability": float(flat_p[~flat_positive].mean()), "observed_prevalence": float(flat_positive.mean())})
        count_rows.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "observed_positive_mean": record["metrics"]["positive_observed_mean"], "predicted_positive_mean": record["metrics"]["positive_predicted_mean"], "bias": record["metrics"]["positive_count_bias"], "mae": record["metrics"]["positive_count_mae"], "rmse": record["metrics"]["positive_count_rmse"], "predicted_p50": record["metrics"]["positive_predicted_p50"], "predicted_p90": record["metrics"]["positive_predicted_p90"], "predicted_p99": record["metrics"]["positive_predicted_p99"]})
        calibration_rows.append({"task_id": record["task_id"], "model_id": record["model_id"], "fold": record["fold"], "seed": record["seed"], "calibration_intercept": record["metrics"]["calibration_intercept"], "calibration_slope": record["metrics"]["calibration_slope"], "observed_prevalence": record["metrics"]["observed_prevalence"], "mean_prediction": record["metrics"]["mean_predicted_probability"], "brier": record["metrics"]["brier"]})
    pd.DataFrame(distribution_rows).to_csv(result_root / "prediction_distribution.csv", index=False); pd.DataFrame(weekly_rows).to_csv(result_root / "weekly_prediction_calibration.csv", index=False); pd.DataFrame(calibration_rows).to_csv(result_root / "calibration_summary.csv", index=False); pd.DataFrame(count_rows).to_csv(result_root / "count_prediction_summary.csv", index=False)
    final_decision = {"completed_task_count": len(records), "models_run": sorted(metrics_frame.model_id.unique().tolist()), "a3_predictors_used": False, "theta_changed_or_reestimated": bool(np.any(np.abs(metrics_frame.theta - THETA) > 1e-12)), "feature_set_changed": False, "f5_f6_used": False, "terminal_later_outcomes_used": False, "feature_selection_reopened": False, "main_merged": False}
    if "N1-E" in set(summary.model_id):
        n1e = summary[summary.model_id == "N1-E"].iloc[0]; final_decision["n1e_valid"] = valid_gate(n1e)
    if "N1-R" in set(summary.model_id):
        n1r = summary[summary.model_id == "N1-R"].iloc[0]; final_decision["n1r_valid"] = valid_gate(n1r)
    if final_decision.get("n1e_valid"):
        final_decision["classification"] = "A0 VALIDITY RESTORED — FREEZE CORRECTED NEURAL BASELINE"
    elif len(summary):
        final_decision["classification"] = "PENDING SEQUENTIAL AUDIT"
    write_json(result_root / "final_architecture_decision.json", final_decision)
    write_json(output_root / "neural_a0_architecture_audit_manifest.json", {"audit_version": "neural-a0-architecture-audit-v1", "completed": len(records), "result_root": result_root, "final_decision": final_decision})
    return {"completed": len(records), "models": sorted(metrics_frame.model_id.unique().tolist()), "final_decision": final_decision}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["prepare", "run", "extend", "finalize"], required=True); parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT_DEFAULT); parser.add_argument("--prior-root", type=Path, default=PRIOR_ROOT_DEFAULT); parser.add_argument("--task-index", type=int); parser.add_argument("--phase", choices=["n2", "n3", "n4"]); parser.add_argument("--loss-objective", choices=["balanced_multitask_loss", "exact_joint_hurdle_nll"], default="exact_joint_hurdle_nll"); parser.add_argument("--cpu", action="store_true"); parser.add_argument("--force", action="store_true"); args = parser.parse_args()
    if args.mode == "prepare": print(json.dumps(jsonable(prepare(args.output_root, args.prior_root)), indent=2, sort_keys=True))
    elif args.mode == "run": require(args.task_index is not None, "--task-index required"); run_one(args.output_root, args.task_index, cpu=args.cpu, force=args.force)
    elif args.mode == "extend": require(args.phase is not None, "--phase required"); print(json.dumps(jsonable(extend(args.output_root, args.phase, args.loss_objective)), indent=2, sort_keys=True))
    else: print(json.dumps(jsonable(finalize(args.output_root)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
