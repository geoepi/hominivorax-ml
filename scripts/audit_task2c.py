#!/usr/bin/env python3
"""Re-score Task-2A baselines and Task-2B/2C neural checkpoints uniformly."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from task2a_pipeline import feature_matrix, fit_nb_glm, nb_predict, seasonal_baseline, target_vector
from task2b_models import GConvGRUHurdleNB, GRUHurdleNB
from task2b_pipeline import (N_CONTEXT, assert_dataset, build_features, load_data, make_masks,
                             split_indices, step_model, write_json)
from task2c_metrics import evaluate_predictions


def load_scaler(root: Path, fold: int) -> tuple[np.ndarray, np.ndarray]:
    path = root / "model_data/scaling" / f"temporal_fold_{fold}.json"
    record = json.loads(path.read_text())
    return np.asarray(record["mean"], dtype=np.float64), np.asarray(record["standard_deviation"], dtype=np.float64)


def save_prediction(path: Path, week_index: np.ndarray, counts: np.ndarray, probability: np.ndarray,
                    conditional: np.ndarray, underlying_mu: np.ndarray, node_ids: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, week_index=week_index.astype(np.int16), node_id=node_ids.astype(np.int32),
                        counts=counts.astype(np.int16), observed_presence=(counts > 0).astype(np.int8),
                        predicted_occurrence_probability=probability.astype(np.float32),
                        predicted_conditional_mean=conditional.astype(np.float32),
                        predicted_underlying_mu=underlying_mu.astype(np.float32),
                        predicted_unconditional_mean=(probability * conditional).astype(np.float32))


def baseline_audit(root: Path) -> list[dict]:
    data = load_data(root); assert_dataset(data)
    dynamic = np.asarray(data["dynamic"]); static = np.asarray(data["static"]); calendar = np.asarray(data["calendar"])
    counts = np.asarray(data["counts"])
    records: list[dict] = []
    pred_dir = root / "predictions/task2c/baselines"
    for fold in range(1, 5):
        train_times, eval_times = split_indices(data, fold)
        x_train = feature_matrix(dynamic, static, calendar, train_times)
        x_eval = feature_matrix(dynamic, static, calendar, eval_times)
        mean, scale = load_scaler(root, fold)
        x_train = ((x_train - mean) / scale).astype(np.float64)
        x_eval = ((x_eval - mean) / scale).astype(np.float64)
        y_train, count_train = target_vector(counts, train_times)
        y_eval, count_eval = target_vector(counts, eval_times)
        y_eval_matrix = counts[eval_times]
        train_prevalence = float(y_train.mean())
        null_p = np.full(y_eval_matrix.shape, train_prevalence, dtype=np.float64)
        null_mu = np.full(y_eval_matrix.shape, float(count_train[count_train > 0].mean()), dtype=np.float64)
        null_metrics = evaluate_predictions(y_eval_matrix, null_p, null_mu, null_mu, 1e6, training_prevalence=train_prevalence, count_score_family="poisson_posthoc")
        save_prediction(pred_dir / f"constant_prevalence_fold{fold}.npz", np.asarray(eval_times), y_eval_matrix, null_p, null_mu, null_mu, np.arange(counts.shape[1]))
        records.append({"model": "constant_prevalence", "loss_objective": "not_applicable", "lambda": None, "fold": fold, "seed": None, "evaluation_regime": "temporal", "source": "task2c_authoritative_evaluator", "metrics": null_metrics})

        p_seasonal, mu_seasonal, _ = seasonal_baseline(train_times, eval_times, data["weeks"], counts)
        p_seasonal = p_seasonal.reshape(y_eval_matrix.shape); mu_seasonal = mu_seasonal.reshape(y_eval_matrix.shape)
        seasonal_metrics = evaluate_predictions(y_eval_matrix, p_seasonal, mu_seasonal, mu_seasonal, 1e6, training_prevalence=train_prevalence, count_score_family="poisson_posthoc")
        save_prediction(pred_dir / f"seasonal_fold{fold}.npz", np.asarray(eval_times), y_eval_matrix, p_seasonal, mu_seasonal, mu_seasonal, np.arange(counts.shape[1]))
        records.append({"model": "seasonal_climatology", "loss_objective": "not_applicable", "lambda": None, "fold": fold, "seed": None, "evaluation_regime": "temporal", "source": "task2c_authoritative_evaluator", "metrics": seasonal_metrics})

        from sklearn.linear_model import LogisticRegression
        occurrence_model = LogisticRegression(solver="lbfgs", max_iter=100, C=1.0, n_jobs=1)
        occurrence_model.fit(x_train, y_train)
        p_model = occurrence_model.predict_proba(x_eval)[:, 1].reshape(y_eval_matrix.shape)
        train_positive = y_train.astype(bool)
        beta, alpha = fit_nb_glm(x_train[train_positive], count_train[train_positive].astype(float))
        mu_model = nb_predict(x_eval, beta).reshape(y_eval_matrix.shape)
        theta = 1.0 / max(float(alpha), 1e-8)
        model_metrics = evaluate_predictions(y_eval_matrix, p_model, mu_model, mu_model, theta, training_prevalence=train_prevalence, count_score_family="untruncated_nb_posthoc_zt_score")
        save_prediction(pred_dir / f"non_spatial_hurdle_fold{fold}.npz", np.asarray(eval_times), y_eval_matrix, p_model, mu_model, mu_model, np.arange(counts.shape[1]))
        records.append({"model": "non_spatial_hurdle_regression", "loss_objective": "not_applicable", "lambda": None, "fold": fold, "seed": None, "evaluation_regime": "temporal", "source": "task2c_authoritative_evaluator", "metrics": model_metrics, "baseline_nb_alpha": alpha})
    return records


def selected_neural_paths(root: Path, experiment: str, pattern: str | None) -> list[Path]:
    directory = root / f"runs/{experiment}"
    if pattern:
        paths = sorted(directory.glob(pattern))
    elif experiment == "task2b":
        paths = sorted(directory.glob("*_temporal_all_*.json"))
    else:
        paths = sorted(directory.glob("*.json"))
    return [path for path in paths if not path.name.startswith("_")]


def neural_audit(root: Path, experiment: str, pattern: str | None, cpu: bool = False) -> list[dict]:
    data = load_data(root); assert_dataset(data)
    device = torch.device("cpu" if cpu else "cuda")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable for neural audit")
    records: list[dict] = []
    for path in selected_neural_paths(root, experiment, pattern):
        record = json.loads(path.read_text())
        if record.get("regime") != "temporal":
            continue
        if experiment == "task2b" and not (record.get("hidden_size") == 64 and record.get("K") == 3 and abs(record.get("dropout", -1) - .1) < 1e-9 and abs(record.get("learning_rate", -1) - .0003) < 1e-12):
            continue
        fold = int(record["fold"])
        features, _ = build_features(data, fold)
        if record.get("feature_variant", "all") == "without_livestock":
            features = np.concatenate([features[:, :, :12], features[:, :, 22:]], axis=2)
        elif record.get("feature_variant", "all") == "without_calendar":
            features = features[:, :, :22]
        model = (GConvGRUHurdleNB(features.shape[2], int(record["hidden_size"]), int(record["K"]), float(record["dropout"])) if record["model"] == "gconvgru" else GRUHurdleNB(features.shape[2], int(record["hidden_size"]), float(record["dropout"]))).to(device)
        checkpoint = torch.load(root / f"models/{experiment}/{record['run_id']}.pt", map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["state_dict"]); model.eval()
        edge_array = data["edges"][["source_node", "target_node"]].to_numpy(np.int64).T.copy()
        edge = torch.as_tensor(edge_array, dtype=torch.long, device=device)
        weight = torch.ones(edge.shape[1], device=device) if record["model"] == "gconvgru" else None
        regime = record.get("regime", "temporal")
        spatial_fold = record.get("spatial_fold")
        train_mask, eval_mask = make_masks(data, fold, regime, spatial_fold)
        eval_indices = np.where(eval_mask.any(axis=1))[0]
        assert len(eval_indices) and not np.any(eval_indices >= len(data["counts"]) - 26)
        last = N_CONTEXT + int(eval_indices[-1]) + 1
        x = torch.as_tensor(features, dtype=torch.float32, device=device)
        hidden = None; logits_rows = []; mu_rows = []; theta_rows = []
        with torch.no_grad():
            for time_index in range(N_CONTEXT):
                _, _, _, hidden = step_model(model, record["model"], x[time_index], edge, weight, hidden)
            for time_index in range(N_CONTEXT, last):
                logits, mu, theta, hidden = step_model(model, record["model"], x[time_index], edge, weight, hidden)
                logits_rows.append(logits.cpu().numpy()); mu_rows.append(mu.cpu().numpy()); theta_rows.append(float(theta.cpu()))
        first = eval_indices[0]
        stop = eval_indices[-1] + 1
        logits = np.asarray(logits_rows)[first:stop]
        underlying_mu = np.asarray(mu_rows)[first:stop]
        theta = float(np.mean(theta_rows))
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        p0 = theta * (np.log(theta) - np.log(theta + np.maximum(underlying_mu, 1e-8)))
        conditional = np.maximum(underlying_mu, 1e-8) / np.maximum(-np.expm1(p0), 1e-8)
        counts = np.asarray(data["counts"])[eval_indices]
        mask = eval_mask[eval_indices]
        train_prevalence = float(np.mean(np.asarray(data["counts"])[train_mask] > 0))
        metrics = evaluate_predictions(counts, p, conditional, underlying_mu, theta, mask=mask, training_prevalence=train_prevalence)
        prediction_path = root / f"predictions/task2c/{experiment}/{record['run_id']}.npz"
        save_prediction(prediction_path, eval_indices, counts, p, conditional, underlying_mu, np.arange(counts.shape[1]))
        records.append({"model": record["model"], "loss_objective": record.get("loss_objective", "balanced_multitask_loss"), "lambda": record.get("positive_loss_multiplier", 1.0), "fold": fold, "seed": record.get("seed"), "evaluation_regime": regime, "spatial_fold": spatial_fold, "source": f"{experiment}_checkpoint", "run_id": record["run_id"], "prediction_path": str(prediction_path), "metrics": metrics, "best_epoch": record.get("best_epoch"), "theta": theta, "training_trajectory": record.get("training_trajectory", [])})
    return records


def write_results(root: Path, records: list[dict], name: str) -> None:
    result_dir = root / "validation/task2c"; result_dir.mkdir(parents=True, exist_ok=True)
    write_json(root / f"manifests/task2c/{name}.json", {"name": name, "records": records, "final_test_predictive_metrics_calculated": False})
    fields = ["model", "loss_objective", "lambda", "fold", "seed", "evaluation_regime", "spatial_fold", "source", "run_id", "prediction_path"]
    metric_names = ["n_node_weeks", "observed_prevalence", "training_prevalence", "mean_predicted_probability", "bernoulli_nll", "brier", "brier_null", "brier_skill", "pr_auc", "pr_auc_over_prevalence", "roc_auc", "calibration_intercept", "calibration_slope", "zt_nb_nll", "positive_count_mae", "positive_count_rmse", "joint_hurdle_nll", "all_cell_mae", "all_cell_rmse", "theta"]
    with (result_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields + metric_names); writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in fields}; row.update({key: record.get("metrics", {}).get(key) for key in metric_names}); writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--experiment", choices=["task2b", "task2c"], default="task2b")
    parser.add_argument("--pattern")
    parser.add_argument("--name")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--skip-baselines", action="store_true")
    args = parser.parse_args()
    records = [] if args.skip_baselines else baseline_audit(args.output_root)
    records.extend(neural_audit(args.output_root, args.experiment, args.pattern, args.cpu))
    name = args.name or f"authoritative_{args.experiment}"
    write_results(args.output_root, records, name)
    print(json.dumps({"records": len(records), "experiment": args.experiment, "final_test_predictive_metrics_calculated": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
