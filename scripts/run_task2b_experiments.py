#!/usr/bin/env python3
"""Small, restartable Task-2B development experiment orchestrator."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


def run_one(repo: Path, output: Path, args: list[str]) -> dict:
    def option(name: str, default: str) -> str:
        return args[args.index(name) + 1] if name in args else default
    model = option("--model", "gconvgru")
    fold = option("--fold", "1")
    regime = option("--regime", "temporal")
    spatial = option("--spatial-fold", "")
    variant = option("--feature-variant", "all")
    seed = option("--seed", "20261002")
    hidden = option("--hidden", "32")
    k = option("--k", "2")
    dropout = option("--dropout", "0.1").replace(".", ".")
    lr = option("--lr", "0.0003")
    spatial_token = "" if not spatial else f"_spatial{spatial}"
    run_id = f"{model}_fold{fold}_{regime}{spatial_token}_{variant}_seed{seed}_h{hidden}_k{k}_d{float(dropout):g}_lr{float(lr):g}"
    existing = output / "runs/task2b" / f"{run_id}.json"
    if existing.exists():
        return json.loads(existing.read_text())
    command = [sys.executable, str(repo / "python/task2b_pipeline.py"), "--output-root", str(output), *args]
    completed = subprocess.run(command, cwd=repo, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"Task-2B run failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}")
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["smoke", "screen", "refine", "finalists", "spatial", "combined", "ablations"], default="smoke")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    output = args.output_root
    records = []
    common = ["--epochs", str(args.epochs or (2 if args.mode == "smoke" else 8)), "--patience", "3", "--chunk", "13", "--write-preprocessor"]
    if args.cpu: common.append("--cpu")
    if args.mode == "smoke":
        for model in ["gru", "gconvgru"]:
            records.append(run_one(args.repo, output, ["--fold", "1", "--model", model, "--seed", "20261002", *common]))
    elif args.mode == "screen":
        # Limited representative-fold screen: width and K are varied with two seeds.
        for model in ["gru", "gconvgru"]:
            for hidden, k in [(32, 2), (32, 3), (64, 2), (64, 3)]:
                for seed in [20261002, 20261003]:
                    records.append(run_one(args.repo, output, ["--fold", "1", "--model", model, "--hidden", str(hidden), "--k", str(k), "--seed", str(seed), *common]))
    elif args.mode == "refine":
        # Learning-rate/dropout refinement for the strongest screen architecture
        # on the representative fold; this is not a final selection.
        for model in ["gru", "gconvgru"]:
            for dropout in [0.0, 0.1, 0.3]:
                for lr in [1e-4, 3e-4, 1e-3]:
                    records.append(run_one(args.repo, output, ["--fold", "1", "--model", model, "--hidden", "64", "--k", "3", "--dropout", str(dropout), "--lr", str(lr), "--seed", "20261002", *common]))
    elif args.mode == "finalists":
        # Matched finalist runs across all four temporal folds and five seeds.
        for model in ["gru", "gconvgru"]:
            for fold in range(1, 5):
                for seed in [20261002, 20261003, 20261004, 20261005, 20261006]:
                    records.append(run_one(args.repo, output, ["--fold", str(fold), "--model", model, "--hidden", "64", "--k", "3", "--dropout", "0.0", "--lr", "0.001", "--seed", str(seed), *common]))
    elif args.mode in ["spatial", "combined"]:
        for model in ["gru", "gconvgru"]:
            for spatial_fold in range(5):
                records.append(run_one(args.repo, output, ["--fold", "1", "--model", model, "--regime", args.mode, "--spatial-fold", str(spatial_fold), "--hidden", "64", "--k", "3", "--seed", "20261002", *common]))
    elif args.mode == "ablations":
        for variant in ["without_livestock", "without_calendar"]:
            records.append(run_one(args.repo, output, ["--fold", "1", "--model", "gconvgru", "--feature-variant", variant, "--hidden", "64", "--k", "3", "--seed", "20261002", *common]))
    table_path = output / f"validation/task2b/task2b_results_{args.mode}.csv"
    table_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "model", "feature_variant", "input_width", "fold", "regime", "spatial_fold", "seed", "hidden_size", "K", "dropout", "learning_rate", "best_epoch", "runtime_seconds"]
    metric_fields = ["joint_hurdle_nll", "bernoulli_nll", "brier", "pr_auc", "roc_auc", "calibration_intercept", "calibration_slope", "zt_nb_nll", "positive_count_mae", "positive_count_rmse", "all_cell_mae", "all_cell_rmse", "fitted_theta"]
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields + metric_fields)
        writer.writeheader()
        for record in records:
            row = {key: record.get(key) for key in fields}
            row.update({key: record.get("metrics", {}).get(key) for key in metric_fields})
            writer.writerow(row)
    summary = {"mode": args.mode, "run_count": len(records), "final_test_predictive_metrics_calculated": False, "results_table": str(table_path), "runs": [record["run_id"] for record in records]}
    (output / "manifests/task2b").mkdir(parents=True, exist_ok=True)
    (output / "manifests/task2b" / f"{args.mode}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
