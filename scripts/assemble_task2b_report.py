#!/usr/bin/env python3
"""Assemble compact Task-2B manifests and fold/seed summaries from run files."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import statistics
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--slurm-job-ids", default="")
    args = parser.parse_args()
    root = args.output_root
    run_paths = sorted((root / "runs/task2b").glob("*.json"))
    records = [json.loads(p.read_text()) for p in run_paths if not p.name.startswith("_")]
    records = [r for r in records if r.get("final_test_predictive_metrics_calculated") is False]
    rows = []
    for record in records:
        row = {key: record.get(key) for key in ["run_id", "model", "feature_variant", "input_width", "fold", "regime", "seed", "hidden_size", "K", "dropout", "learning_rate", "best_epoch", "runtime_seconds"]}
        row.update(record.get("metrics", {}))
        row.pop("reliability", None)
        rows.append(row)
    validation = root / "validation/task2b"; validation.mkdir(parents=True, exist_ok=True)
    if rows:
        keys = sorted({key for row in rows for key in row})
        with (validation / "task2b_results_all.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys); writer.writeheader(); writer.writerows(rows)
    summary = {}
    for model in sorted({r.get("model") for r in records}):
        selected = [r for r in records if r.get("model") == model and r.get("regime") == "temporal" and r.get("feature_variant", "all") == "all"]
        metrics = {}
        for metric in ["joint_hurdle_nll", "bernoulli_nll", "brier", "pr_auc", "roc_auc", "calibration_intercept", "calibration_slope", "zt_nb_nll", "positive_count_mae", "positive_count_rmse", "all_cell_mae", "all_cell_rmse", "fitted_theta"]:
            values = [float(r["metrics"][metric]) for r in selected if r.get("metrics", {}).get(metric) is not None]
            if values: metrics[metric] = {"mean": statistics.mean(values), "median": statistics.median(values), "sd": statistics.stdev(values) if len(values) > 1 else 0.0, "min": min(values), "n": len(values)}
        fold4 = [r["metrics"] for r in selected if int(r.get("fold", -1)) == 4]
        summary[model] = {"run_count": len(selected), "metrics": metrics, "fold4_metrics": fold4}
    manifest = {
        "status": "completed_development_only" if records else "no_runs",
        "slurm_job_ids": [item for item in args.slurm_job_ids.split(",") if item],
        "run_count": len(records),
        "models": summary,
        "final_test_predictive_metrics_calculated": False,
        "final_test_interval": ["2026-W04", "2026-W29"],
        "results_table": str(validation / "task2b_results_all.csv"),
        "git_sha": json.loads((root / "model_data/manifests/dataset_manifest.json").read_text())["git_sha"],
        "dataset_manifest_path": str(root / "model_data/manifests/dataset_manifest.json"),
        "feature_names": json.loads((root / "model_data/manifests/dataset_manifest.json").read_text())["feature_names"],
        "array_shapes": json.loads((root / "model_data/manifests/dataset_manifest.json").read_text())["array_shapes"],
        "warmup_weeks": 52,
        "tbptt_weeks": 13,
        "gradient_clip_norm": 1.0,
        "evaluation_mode": "development",
        "selected_finalist": {
            "gconvgru": {"model": "gconvgru", "feature_variant": "all", "hidden_size": 64, "K": 3, "dropout": 0.1, "learning_rate": 0.0003, "temporal_runs": 20, "folds": 4, "seeds_per_fold": 5},
            "gru_comparator": {"model": "gru", "feature_variant": "all", "hidden_size": 64, "K": 3, "dropout": 0.1, "learning_rate": 0.0003, "temporal_runs": 20, "folds": 4, "seeds_per_fold": 5},
            "selection_basis": "complete four-fold five-seed development evaluation; representative-fold refinement retained as sensitivity evidence",
        },
    }
    manifests = root / "manifests/task2b"; manifests.mkdir(parents=True, exist_ok=True)
    (manifests / "task2b_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
