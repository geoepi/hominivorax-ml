#!/usr/bin/env python3
"""Restricted final structured A0 versus A3 comparison.

This wrapper reuses the validated fixed-theta structured augmentation fitter,
but exposes only the frozen A0 and A3 tasks.  It does not run A1/A2 screening,
neural models, graph models, or any terminal/prospective evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUGMENTATION_SCRIPT = REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts" / "run_predictor_augmentation.py"
MODULE_SPEC = importlib.util.spec_from_file_location("validated_structured_augmentation", AUGMENTATION_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Cannot load validated structured fitter: {AUGMENTATION_SCRIPT}")
AUG = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUG)

# Restrict the imported fitter to the approved direct comparison.
AUG.MODELS = {"A0": [], "A3": list(AUG.ADDED_FEATURES)}

EXPECTED_TRANSFORMATIONS = {
    "road_density": "log1p",
    "night_illumination": "log1p",
    "clay_0_15": "identity",
    "water_difference_wv0033_minus_wv0010_0_15": "identity",
}
EXPECTED_FEATURES = list(AUG.BASE_FEATURES) + list(AUG.ADDED_FEATURES)
METRIC_COLUMNS = list(AUG.METRIC_COLUMNS) + ["zt_nb_nll"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_prepared_output(output: Path) -> None:
    manifest_path = output / "manifests" / "augmentation_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("feature_count_v2a") != 30:
        raise RuntimeError("STOP: frozen V2-A feature count is not 30")
    if manifest.get("added_features") != list(AUG.ADDED_FEATURES):
        raise RuntimeError("STOP: A3 additions differ from the frozen four-feature specification")
    if manifest.get("transformations") != EXPECTED_TRANSFORMATIONS:
        raise RuntimeError(f"STOP: frozen transformations differ: {manifest.get('transformations')}")
    task_manifest = pd.read_csv(output / "model_task_manifest.csv")
    if len(task_manifest) != 8 or set(task_manifest["model"]) != {"A0", "A3"}:
        raise RuntimeError("STOP: restricted comparison must contain exactly eight A0/A3 tasks")
    if sorted(task_manifest["task_id"].astype(int).tolist()) != list(range(1, 9)):
        raise RuntimeError("STOP: task IDs are not the expected eight-task restartable matrix")
    if not np.array_equal(np.sort(task_manifest.loc[task_manifest.model == "A0", "fold"].astype(int)), np.arange(1, 5)):
        raise RuntimeError("STOP: A0 tasks do not cover F1-F4 exactly")
    if not np.array_equal(np.sort(task_manifest.loc[task_manifest.model == "A3", "fold"].astype(int)), np.arange(1, 5)):
        raise RuntimeError("STOP: A3 tasks do not cover F1-F4 exactly")


def prepare(args: argparse.Namespace) -> None:
    AUG.prepare(args)
    validate_prepared_output(args.output_root)
    print(json.dumps({"status": "prepared", "models": ["A0", "A3"], "tasks": 8}, indent=2))


def baseline_gate(args: argparse.Namespace) -> None:
    output = args.output_root
    reference = pd.read_csv(args.reference_metrics).set_index("fold")
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    rows: list[dict[str, Any]] = []
    for fold in range(1, 5):
        task_id = (fold - 1) * 2 + 1
        task = manifest.loc[manifest["task_id"].astype(int) == task_id].iloc[0]
        result_path = output / str(task["output_path"])
        if not result_path.exists():
            raise RuntimeError(f"STOP: missing A0 result for fold {fold}: {result_path}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed" or result.get("model") != "A0" or int(result.get("fold", -1)) != fold:
            raise RuntimeError(f"STOP: invalid A0 result for fold {fold}")
        for metric in AUG.METRIC_COLUMNS:
            expected = float(reference.loc[fold, metric])
            observed = float(result["metrics"][metric])
            difference = abs(observed - expected)
            rows.append({"fold": fold, "metric": metric, "reference": expected, "reproduced": observed, "absolute_difference": difference, "tolerance": 1e-9, "within_tolerance": bool(difference <= 1e-9)})
    comparison = pd.DataFrame(rows)
    comparison.to_csv(output / "baseline_reproduction.csv", index=False)
    passed = bool(comparison["within_tolerance"].all())
    gate = {
        "status": "baseline_reproduction_passed" if passed else "STOP_BASELINE_REPRODUCTION_FAILED",
        "pass": passed,
        "feature_count": 30,
        "folds": "F1-F4 only",
        "objective": "exact_joint_hurdle_nll",
        "penalty": AUG.PENALTY,
        "theta": AUG.FIXED_THETA,
        "theta_fixed": True,
        "reference_metrics": str(args.reference_metrics),
        "reference_sha256": sha256_file(args.reference_metrics),
        "terminal_response_loaded": False,
        "stgnn_fitted": False,
    }
    write_json(output / "baseline_gate.json", gate)
    write_json(output / "a0_reference_manifest.json", {
        "model": "A0",
        "feature_count": 30,
        "feature_order": list(AUG.BASE_FEATURES),
        "reference_metrics_path": str(args.reference_metrics),
        "reference_sha256": sha256_file(args.reference_metrics),
        "reference_metrics": reference.reset_index().to_dict(orient="records"),
        "reproduction_passed": passed,
        "metric_tolerance": 1e-9,
        "objective": "exact_joint_hurdle_nll",
        "penalty": AUG.PENALTY,
        "theta": AUG.FIXED_THETA,
        "theta_fixed": True,
        "folds": "F1-F4 only",
    })
    print(json.dumps(gate, indent=2))
    if not passed:
        raise SystemExit("STOP: A0 baseline reproduction failed")


def worker(args: argparse.Namespace) -> None:
    AUG.worker(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "baseline", "worker"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--front-features", type=Path)
    parser.add_argument("--anthropogenic-features", type=Path)
    parser.add_argument("--soil-features", type=Path)
    parser.add_argument("--reference-metrics", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        required = (args.model_output, args.front_features, args.anthropogenic_features, args.soil_features, args.reference_metrics)
        if any(value is None for value in required):
            parser.error("prepare requires model/output, front, anthropogenic, soil, and reference paths")
        prepare(args)
    elif args.mode == "baseline":
        if args.reference_metrics is None:
            parser.error("baseline requires --reference-metrics")
        baseline_gate(args)
    else:
        if args.task_id is None:
            parser.error("worker requires --task-id")
        worker(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
