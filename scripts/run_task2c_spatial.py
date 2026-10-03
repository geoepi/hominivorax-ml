#!/usr/bin/env python3
"""Run preferred Task-2C loss settings under spatial and combined masks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--loss-objective", choices=["balanced_multitask_loss", "exact_joint_hurdle_nll"], required=True)
    parser.add_argument("--positive-loss-multiplier", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--epochs", type=int, default=12)
    args = parser.parse_args()
    runs = []
    common = [
        sys.executable, str(args.repo / "python/task2b_pipeline.py"),
        "--output-root", str(args.output_root), "--experiment", "task2c",
        "--hidden", "64", "--k", "3", "--dropout", "0.1", "--lr", "0.0003",
        "--seed", str(args.seed), "--epochs", str(args.epochs), "--patience", "3", "--chunk", "13",
        "--loss-objective", args.loss_objective, "--positive-loss-multiplier", str(args.positive_loss_multiplier),
    ]
    for model in ("gru", "gconvgru"):
        for spatial_fold in range(5):
            command = common + ["--model", model, "--fold", "1", "--regime", "spatial", "--spatial-fold", str(spatial_fold)]
            runs.append(subprocess.run(command, cwd=args.repo, check=True, text=True, capture_output=True).stdout)
        for fold in range(1, 5):
            for spatial_fold in range(5):
                command = common + ["--model", model, "--fold", str(fold), "--regime", "combined", "--spatial-fold", str(spatial_fold)]
                runs.append(subprocess.run(command, cwd=args.repo, check=True, text=True, capture_output=True).stdout)
    manifest_dir = args.output_root / "manifests/task2c"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "spatial_combined.json").write_text(json.dumps({
        "loss_objective": args.loss_objective,
        "positive_loss_multiplier": args.positive_loss_multiplier,
        "seed": args.seed,
        "run_count": len(runs),
        "regimes": ["spatial", "combined"],
        "final_test_predictive_metrics_calculated": False,
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
