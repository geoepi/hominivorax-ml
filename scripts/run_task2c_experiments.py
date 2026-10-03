#!/usr/bin/env python3
"""Restartable Task-2C loss-objective experiments.

This deliberately keeps the Task-2B architecture fixed and varies only the
approved hurdle-loss objective and positive-count multiplier.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


SEEDS_STAGE1 = [20261002, 20261003]
SEEDS_STAGE2 = [20261002, 20261003, 20261004, 20261005, 20261006]


def run_one(repo: Path, output: Path, model: str, fold: int, seed: int, objective: str, multiplier: float, epochs: int) -> dict:
    lambda_token = f"{multiplier:g}"
    run_id = f"{model}_fold{fold}_temporal_all_seed{seed}_h64_k3_d0.1_lr0.0003_loss{objective}_lam{lambda_token}"
    path = output / "runs/task2c" / f"{run_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    command = [
        sys.executable, str(repo / "python/task2b_pipeline.py"),
        "--output-root", str(output), "--experiment", "task2c",
        "--fold", str(fold), "--model", model, "--hidden", "64", "--k", "3",
        "--dropout", "0.1", "--lr", "0.0003", "--seed", str(seed),
        "--epochs", str(epochs), "--patience", "3", "--chunk", "13",
        "--loss-objective", objective, "--positive-loss-multiplier", str(multiplier),
    ]
    completed = subprocess.run(command, cwd=repo, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"Task-2C run failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["stage1", "stage2"], required=True)
    parser.add_argument("--objectives", default="exact_joint_hurdle_nll,balanced_multitask_loss:1,balanced_multitask_loss:0.1,balanced_multitask_loss:0.25")
    parser.add_argument("--epochs", type=int, default=12)
    args = parser.parse_args()
    if args.mode == "stage1":
        folds, seeds = [2, 4], SEEDS_STAGE1
    else:
        folds, seeds = [1, 2, 3, 4], SEEDS_STAGE2
    objectives: list[tuple[str, float]] = []
    for token in args.objectives.split(","):
        parts = token.split(":")
        objective = parts[0]
        multiplier = float(parts[1]) if len(parts) > 1 else 1.0
        if objective == "exact_joint_hurdle_nll":
            multiplier = 1.0
        objectives.append((objective, multiplier))
    if args.mode == "stage2" and len(objectives) > 2:
        raise ValueError("Stage 2 accepts at most two loss objectives")
    records: list[dict] = []
    for objective, multiplier in objectives:
        for model in ["gru", "gconvgru"]:
            for fold in folds:
                for seed in seeds:
                    records.append(run_one(args.repo, args.output_root, model, fold, seed, objective, multiplier, args.epochs))
    result_dir = args.output_root / "validation/task2c"
    result_dir.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "model", "fold", "seed", "loss_objective", "positive_loss_multiplier", "best_epoch", "runtime_seconds"]
    metric_fields = ["joint_hurdle_nll", "bernoulli_nll", "brier", "pr_auc", "roc_auc", "calibration_intercept", "calibration_slope", "zt_nb_nll", "positive_count_mae", "positive_count_rmse", "all_cell_mae", "all_cell_rmse", "fitted_theta"]
    path = result_dir / f"task2c_results_{args.mode}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields + metric_fields)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in fields}
            row.update({key: record.get("metrics", {}).get(key) for key in metric_fields})
            writer.writerow(row)
    manifest_dir = args.output_root / "manifests/task2c"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "mode": args.mode, "run_count": len(records), "objectives": [{"loss_objective": o, "positive_loss_multiplier": m} for o, m in objectives],
        "folds": folds, "seeds": seeds, "architecture": {"hidden": 64, "K": 3, "dropout": 0.1, "learning_rate": 0.0003},
        "results_table": str(path), "final_test_predictive_metrics_calculated": False,
        "runs": [record["run_id"] for record in records],
    }
    (manifest_dir / f"{args.mode}.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
