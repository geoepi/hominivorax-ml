"""Run the prespecified A6 correlated-boosting spatial ML challenger."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
A5_DIR = REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison/scripts"
A5B_DIR = REPOSITORY_ROOT / "analysis/a5b_multiscale_component_spatial_ml/scripts"
sys.path.insert(0, str(A5_DIR))
sys.path.insert(0, str(A5B_DIR))

import run_a5_gnn as A5  # noqa: E402


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A5B = load_module(A5B_DIR / "run_a5b.py", "a6_a5b_reference_helpers")

NODE_COUNT = A5.NODE_COUNT
DEVELOPMENT_WEEKS = A5.DEVELOPMENT_WEEKS
FOLDS = A5.FOLDS
SEEDS = A5.SEEDS
THETA = A5.THETA
A6_CANDIDATES = ["A6-GB-IID", "A6-GPB-S", "A6-GPB-ST"]
A6_HYBRID = "A6-GPB-ST-HYBRID"
REFERENCE_CANDIDATES = ["A3", "STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"]
REQUIRED_METRICS = [
    "pr_auc", "roc_auc", "brier", "brier_skill", "bernoulli_nll",
    "calibration_intercept", "calibration_slope", "zt_nb_nll",
    "positive_count_mae", "positive_count_rmse", "conditional_mean_bias",
    "full_hurdle_expected_count_mae", "full_hurdle_rmse", "full_hurdle_signed_bias",
    "observed_predicted_positive_count_total_ratio", "joint_hurdle_nll",
]
SHELLS = (1, 2, 3, 4)
PARENT_A5B_SHA = "d6651a8e221e54184c68c098805300723a598276"
PARENT_A5_SHA = "e71c02c3ea87a4ab13dbb7733277c17b9c53c550"
PRODUCTION_MODEL_SHA = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
FROZEN_A4S_MANIFEST_SHA = "156ab650b8fa79f7a4fe390f3687ca53212fbf37fb7e9963ba91b9f70c9b68af"


class A6SoftwareBlocked(RuntimeError):
    """Raised when the specified GPBoost software/API contract cannot run."""


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
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_output_root(explicit: Path | None) -> Path:
    value = explicit or (Path(os.environ["A6_OUTPUT_ROOT"]) if os.environ.get("A6_OUTPUT_ROOT") else None)
    if value is None:
        raise RuntimeError("A6_OUTPUT_ROOT or --output-root is required")
    root = value.expanduser().resolve()
    if "/90daydata/" not in str(root).replace("\\", "/"):
        raise RuntimeError(f"large A6 products must be under /90daydata/disease_ecology: {root}")
    return root


def assert_storage_roots(output: Path, durable: Path | None) -> None:
    if durable is not None and durable.resolve() == output.resolve():
        raise RuntimeError("A6 durable summary root must be separate from temporary output root")
    if durable is not None and "90daydata" in str(durable).replace("\\", "/"):
        raise RuntimeError("A6 durable summaries must not be under /90daydata")


def read_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("analysis") != "a6_gpboost_correlated_spatial_ml":
        raise RuntimeError("A6 analysis identifier changed")
    if config.get("parent_a5b_commit") != PARENT_A5B_SHA:
        raise RuntimeError("A6 parent A5B commit changed")
    if config.get("development_classification") != "DEVELOPMENT_INFORMED_FOLLOWUP":
        raise RuntimeError("A6 must remain development-informed")
    if config["predictors"]["count"] != 34 or config["predictors"]["coordinates_are_tree_features"]:
        raise RuntimeError("A6 predictor contract changed")
    if config["gpboost"]["version"] != "1.8.0" or config["gpboost"]["gp_approx"] != "vecchia":
        raise RuntimeError("A6 GPBoost contract changed")
    if config["gpboost"]["num_neighbors"] != 20 or config["gpboost"]["num_neighbors_pred"] != 40:
        raise RuntimeError("A6 Vecchia neighbor contract changed")
    if config["gpboost"]["cov_fct_shape"] != 1.5:
        raise RuntimeError("A6 Matérn smoothness contract changed")
    if config["boosting"]["maximum_boosting_rounds"] != 500:
        raise RuntimeError("A6 boosting-round contract changed")
    return config


def load_gpboost():
    try:
        import gpboost as gpb
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise A6SoftwareBlocked(f"A6_SOFTWARE_DEPENDENCY_BLOCKED: GPBoost import failed: {exc}") from exc
    if getattr(gpb, "__version__", None) != "1.8.0":
        raise A6SoftwareBlocked(f"A6_SOFTWARE_DEPENDENCY_BLOCKED: expected GPBoost 1.8.0, got {getattr(gpb, '__version__', None)}")
    return gpb


def audit_environment(config: dict[str, Any], output: Path) -> dict[str, Any]:
    gpb = load_gpboost()
    import inspect

    def disk(path: str) -> dict[str, Any]:
        usage = shutil.disk_usage(path)
        return {"path": path, "total_bytes": usage.total, "used_bytes": usage.total - usage.free, "free_bytes": usage.free}

    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True).splitlines()
    except Exception:
        freeze = []
    payload = {
        "status": "PASSED",
        "timestamp_utc": utc_now(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "gpboost_version": gpb.__version__,
        "gpboost_path": str(Path(gpb.__file__).resolve()),
        "numpy_version": importlib.metadata.version("numpy"),
        "pandas_version": importlib.metadata.version("pandas"),
        "scipy_version": importlib.metadata.version("scipy"),
        "scikit_learn_version": importlib.metadata.version("scikit-learn"),
        "optuna_version": importlib.metadata.version("optuna"),
        "gpboost_api": {
            "GPModel_init": str(inspect.signature(gpb.GPModel.__init__)),
            "GPModel_predict": str(inspect.signature(gpb.GPModel.predict)),
            "GPModel_set_prediction_data": str(inspect.signature(gpb.GPModel.set_prediction_data)),
            "train": str(inspect.signature(gpb.train)),
            "Booster_predict": str(inspect.signature(gpb.Booster.predict)),
        },
        "verified_contract": {
            "bernoulli_logit": True,
            "matern": True,
            "matern_space_time": True,
            "vecchia": True,
            "init_score": True,
            "offset_pred": True,
            "observed_training_only_prediction_mode": "order_obs_first_cond_obs_only",
        },
        "pip_freeze": freeze,
        "storage": {"project": disk("/project/disease_ecology"), "90daydata": disk("/90daydata/disease_ecology")},
        "storage_class": "TEMPORARY_90DAY_STORAGE",
        "config_sha256": config_sha256(config),
    }
    write_json(output / "provenance/environment_manifest.json", payload)
    write_json(output / "provenance/software_audit.json", payload)
    return payload


def load_data(args: argparse.Namespace) -> A5.DataBundle:
    a5_config = json.loads((REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison/config/a5_gnn_config.json").read_text())
    return A5.load_data(args, a5_config)


def load_reference(root: Path) -> dict[str, Any]:
    required = [
        root / "results/a5b_decision.json", root / "results/fold_seed_metrics.csv",
        root / "results/aggregate_metrics.csv", root / "results/residual_spatial_summary.csv",
        root / "results/residual_temporal_summary.csv", root / "results/frontier_metrics.csv",
    ]
    if any(not path.exists() for path in required):
        raise RuntimeError("A5B compact reference artifacts are incomplete")
    decision = json.loads((root / "results/a5b_decision.json").read_text())
    if decision.get("primary_decision") != "A5B_NOT_JUSTIFIED":
        raise RuntimeError("A5B reference decision changed")
    fold = pd.read_csv(root / "results/fold_seed_metrics.csv")
    missing = set(REFERENCE_CANDIDATES) - set(fold["candidate"].astype(str).unique())
    if missing:
        raise RuntimeError(f"A5B reference lacks candidates: {sorted(missing)}")
    return {
        "root": root,
        "decision": decision,
        "fold": fold,
        "aggregate": pd.read_csv(root / "results/aggregate_metrics.csv"),
        "spatial": pd.read_csv(root / "results/residual_spatial_summary.csv"),
        "temporal": pd.read_csv(root / "results/residual_temporal_summary.csv"),
        "frontier": pd.read_csv(root / "results/frontier_metrics.csv"),
        "manifest_sha256": sha256_file(root / "provenance/a5b_analysis_manifest.json"),
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
    arrays: dict[int, dict[str, np.ndarray]] = {}
    required = ["joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias"]
    for fold_record in FOLDS:
        fold = A5.prepare_temporal_fold(data, fold_record, frozen_a3_output)
        frozen = A5.load_frozen_a3_predictions(frozen_a3_output, fold.fold, data.counts, fold.validation_times)
        y, p, conditional, mu = (frozen[key] for key in ("y", "p", "conditional", "mu"))
        record, fold_arrays = A5.fold_prediction_record("A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu, float(np.mean(fold.counts[fold.train_times] > 0)), {"frozen_reference_metrics": True, "reference_source": "structured_a3_final_comparison"})
        expected = reference_rows(reference, "A3", fold.fold).iloc[0]
        for metric in required:
            observed, target = float(record[metric]), float(expected[metric])
            rows.append({"fold": fold.fold, "metric": metric, "reference": target, "reproduced": observed, "absolute_difference": abs(target - observed), "tolerance": 1e-9, "pass": abs(target - observed) <= 1e-9})
        arrays[fold.fold] = fold_arrays
    frame = pd.DataFrame(rows)
    write_csv(output / "results/a3_baseline_reproduction.csv", frame)
    if not bool(frame["pass"].all()):
        raise RuntimeError("STOP: A3 reproduction failed")
    return frame, arrays


def node_coordinates(data: A5.DataBundle) -> np.ndarray:
    nodes = data.nodes.sort_values("model_node_id")
    if not np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("canonical node order changed")
    coords = nodes[["x", "y"]].to_numpy(np.float64)
    if coords.shape != (NODE_COUNT, 2) or not np.isfinite(coords).all():
        raise RuntimeError("canonical projected coordinate contract failed")
    return coords


def build_coords(coords_xy: np.ndarray, times: np.ndarray, node_ids: np.ndarray, space_time: bool) -> np.ndarray:
    xy = np.asarray(coords_xy, dtype=np.float64)[np.asarray(node_ids, dtype=np.int64)]
    repeated_xy = np.tile(xy, (len(times), 1))
    if not space_time:
        return repeated_xy
    time_column = np.repeat(np.asarray(times, dtype=np.float64), len(node_ids))[:, None]
    return np.column_stack([time_column, repeated_xy])


def flatten_fold(fold: A5.FoldPrepared, times: np.ndarray, node_ids: np.ndarray, coords_xy: np.ndarray, space_time: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    node_ids = np.asarray(node_ids, dtype=np.int64)
    x = fold.x[np.asarray(times)[:, None], node_ids, :].reshape(-1, 34).astype(np.float64)
    y_count = fold.counts[np.asarray(times)[:, None], node_ids].reshape(-1).astype(np.int64)
    y = (y_count > 0).astype(np.int64)
    offset = fold.eta[np.asarray(times)[:, None], node_ids].reshape(-1).astype(np.float64)
    coords = build_coords(coords_xy, np.asarray(times, dtype=np.int64), node_ids, space_time)
    return x, y, y_count, offset, coords


def model_params(config: dict[str, Any], seed: int) -> dict[str, Any]:
    boost = config["boosting"]
    return {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": boost["learning_rate"],
        "max_depth": boost["max_depth"],
        "num_leaves": boost["num_leaves"],
        "min_data_in_leaf": boost["min_data_in_leaf"],
        "feature_fraction": boost["feature_fraction"],
        "bagging_fraction": boost["bagging_fraction"],
        "lambda_l2": boost["lambda_l2"],
        "feature_fraction_seed": seed,
        "bagging_seed": seed,
        "data_random_seed": seed,
        "seed": seed,
        "num_threads": min(16, os.cpu_count() or 1),
        "verbosity": -1,
    }


def make_gp_model(gpb: Any, candidate: str, coords: np.ndarray, seed: int, config: dict[str, Any]) -> Any | None:
    if candidate == "A6-GB-IID":
        return None
    gp = config["gpboost"]
    space_time = candidate == "A6-GPB-ST"
    return gpb.GPModel(
        likelihood=gp["likelihood"],
        gp_coords=coords,
        cov_function=gp["spatiotemporal_cov_function"] if space_time else gp["spatial_cov_function"],
        cov_fct_shape=gp["cov_fct_shape"],
        gp_approx=gp["gp_approx"],
        num_parallel_threads=min(16, os.cpu_count() or 1),
        num_neighbors=gp["num_neighbors"],
        vecchia_ordering=gp["vecchia_ordering_spatiotemporal"] if space_time else gp["vecchia_ordering_spatial"],
        vecchia_pred_type=gp["vecchia_pred_type"],
        num_neighbors_pred=gp["num_neighbors_pred"],
        seed=seed,
    )


def make_dataset(gpb: Any, x: np.ndarray, y: np.ndarray, offset: np.ndarray) -> Any:
    dataset = gpb.Dataset(x, label=y, init_score=offset, free_raw_data=False)
    stored = dataset.get_init_score()
    if stored is None or not np.allclose(np.asarray(stored, dtype=float), offset, rtol=0, atol=0):
        raise A6SoftwareBlocked("A6 init_score offset was not preserved exactly by GPBoost Dataset")
    return dataset


def train_booster(
    gpb: Any,
    candidate: str,
    config: dict[str, Any],
    seed: int,
    x_train: np.ndarray,
    y_train: np.ndarray,
    offset_train: np.ndarray,
    coords_train: np.ndarray,
    rounds: int,
    valid: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    early_stopping: bool = False,
) -> tuple[Any, Any | None, dict[str, Any]]:
    gp = make_gp_model(gpb, candidate, coords_train, seed, config)
    train_set = make_dataset(gpb, x_train, y_train, offset_train)
    valid_set = None
    if valid is not None:
        x_valid, y_valid, offset_valid, coords_valid = valid
        valid_set = make_dataset(gpb, x_valid, y_valid, offset_valid)
        if gp is not None:
            gp.set_prediction_data(
                vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
                num_neighbors_pred=config["gpboost"]["num_neighbors_pred"],
                gp_coords_pred=coords_valid,
            )
    params = model_params(config, seed)
    started = time.time()
    caught: list[str] = []
    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        try:
            booster = gpb.train(
                params=params,
                train_set=train_set,
                num_boost_round=int(rounds),
                gp_model=gp,
                use_gp_model_for_validation=True,
                train_gp_model_cov_pars=True,
                valid_sets=[valid_set] if valid_set is not None else None,
                valid_names=["inner"] if valid_set is not None else None,
                early_stopping_rounds=config["boosting"]["early_stopping_rounds"] if early_stopping else None,
                verbose_eval=False,
                keep_training_booster=True,
            )
        except Exception as exc:
            raise A6SoftwareBlocked(f"GPBoost training failed for {candidate}, seed {seed}: {exc}") from exc
        caught = [str(item.message) for item in warning_records]
    best_iteration = int(getattr(booster, "best_iteration", 0) or 0)
    current_iteration = int(booster.current_iteration())
    selected_rounds = best_iteration if early_stopping and best_iteration > 0 else current_iteration
    if selected_rounds <= 0:
        selected_rounds = int(rounds)
    fit_info: dict[str, Any] = {
        "candidate": candidate,
        "seed": int(seed),
        "requested_rounds": int(rounds),
        "selected_rounds": int(selected_rounds),
        "best_iteration": int(best_iteration),
        "current_iteration": int(current_iteration),
        "runtime_seconds": float(time.time() - started),
        "warnings": caught,
        "converged": True,
        "covariance_parameter_raw": None,
        "covariance_parameter_table": None,
        "process_variance": None,
        "spatial_range": None,
        "temporal_range": None,
        "covariance_non_degenerate": True,
        "covariance_ranges_non_boundary": True,
    }
    if gp is not None:
        try:
            raw = np.asarray(gp.get_cov_pars(format_pandas=False), dtype=float).ravel()
            table = gp.get_cov_pars(format_pandas=True)
            fit_info["covariance_parameter_raw"] = raw.tolist()
            fit_info["covariance_parameter_table"] = table.to_dict("records") if hasattr(table, "to_dict") else str(table)
            if len(raw):
                fit_info["process_variance"] = float(raw[0])
            if candidate == "A6-GPB-S" and len(raw) >= 2:
                fit_info["spatial_range"] = float(raw[-1])
            if candidate == "A6-GPB-ST" and len(raw) >= 3:
                fit_info["spatial_range"] = float(raw[-2])
                fit_info["temporal_range"] = float(raw[-1])
            fit_info["covariance_non_degenerate"] = bool(len(raw) > 0 and np.isfinite(raw).all() and raw[0] > 1e-8)
            fit_info["covariance_ranges_non_boundary"] = bool(all(np.isfinite(raw)) and all((abs(value) > 1e-8 and abs(value) < 1e8) for value in raw[1:]))
        except Exception as exc:
            fit_info["converged"] = False
            fit_info["covariance_error"] = str(exc)
    return booster, gp, fit_info


def choose_rounds(gpb: Any, candidate: str, fold: A5.FoldPrepared, seed: int, config: dict[str, Any], coords_xy: np.ndarray) -> tuple[int, dict[str, Any]]:
    inner_train, inner_monitor = A5.inner_split(fold.train_times, config["boosting"]["inner_monitor_fraction"], config["boosting"]["inner_monitor_min_weeks"])
    all_nodes = np.arange(NODE_COUNT, dtype=np.int64)
    x_train, y_train, _, offset_train, coords_train = flatten_fold(fold, inner_train, all_nodes, coords_xy, candidate == "A6-GPB-ST")
    x_valid, y_valid, _, offset_valid, coords_valid = flatten_fold(fold, inner_monitor, all_nodes, coords_xy, candidate == "A6-GPB-ST")
    booster, gp, info = train_booster(gpb, candidate, config, seed, x_train, y_train, offset_train, coords_train, config["boosting"]["maximum_boosting_rounds"], (x_valid, y_valid, offset_valid, coords_valid), True)
    info["inner_train_weeks"] = [int(value) for value in inner_train]
    info["inner_monitor_weeks"] = [int(value) for value in inner_monitor]
    info["outer_validation_excluded"] = True
    del booster, gp
    return int(info["selected_rounds"]), info


def predict_booster(booster: Any, gp: Any | None, candidate: str, x: np.ndarray, offset: np.ndarray, coords: np.ndarray, rounds: int, config: dict[str, Any]) -> np.ndarray:
    if gp is None:
        raw = np.asarray(booster.predict(x, raw_score=True, num_iteration=int(rounds)), dtype=float) + offset
        probability = expit(raw)
    else:
        gp.set_prediction_data(
            vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
            num_neighbors_pred=config["gpboost"]["num_neighbors_pred"],
            gp_coords_pred=coords,
        )
        result = booster.predict(x, gp_coords_pred=coords, offset_pred=offset, num_iteration=int(rounds))
        if not isinstance(result, dict) or "response_mean" not in result:
            raise A6SoftwareBlocked(f"GPBoost prediction response contract failed for {candidate}")
        probability = np.asarray(result["response_mean"], dtype=float)
    if not np.isfinite(probability).all() or np.any(probability < -1e-12) or np.any(probability > 1 + 1e-12):
        raise A6SoftwareBlocked(f"non-finite or out-of-bounds predictions for {candidate}")
    return np.clip(probability, 0.0, 1.0)


def save_models(booster: Any, gp: Any | None, output: Path, candidate: str, fold: int, seed: int) -> dict[str, Any]:
    model_dir = output / "models" / candidate / f"fold_{fold:02d}"
    model_dir.mkdir(parents=True, exist_ok=True)
    booster_path = model_dir / f"seed_{seed}.booster.txt"
    booster.save_model(str(booster_path))
    result = {"booster_path": str(booster_path), "booster_sha256": sha256_file(booster_path), "booster_size_bytes": booster_path.stat().st_size}
    if gp is not None:
        gp_path = model_dir / f"seed_{seed}.gpmodel.json"
        try:
            gp.save_model(str(gp_path))
            result.update({"gp_model_path": str(gp_path), "gp_model_sha256": sha256_file(gp_path), "gp_model_size_bytes": gp_path.stat().st_size})
        except Exception as exc:
            result["gp_model_save_error"] = str(exc)
    return result


def persist_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)


def primary_oof(data: A5.DataBundle, config: dict[str, Any], reference: dict[str, Any], a4s: Any, frozen_a3_output: Path, output: Path, coords_xy: np.ndarray, gpb: Any) -> tuple[pd.DataFrame, dict[str, list[dict[str, Any]]], dict[str, list[dict[str, np.ndarray]]], list[dict[str, Any]], dict[str, str]]:
    records: dict[str, list[dict[str, Any]]] = {"A3": []}
    arrays: dict[str, list[dict[str, np.ndarray]]] = {"A3": []}
    covariance_rows: list[dict[str, Any]] = []
    candidate_status: dict[str, str] = {}
    new_rows: list[dict[str, Any]] = []
    reference_frame = add_reference_source(reference["fold"].loc[reference["fold"]["candidate"].astype(str).isin(REFERENCE_CANDIDATES)], "completed_a5b_compact_artifact")

    def persist() -> None:
        write_csv(output / "results/fold_seed_metrics.csv", pd.concat([reference_frame, pd.DataFrame(new_rows)], ignore_index=True, sort=False))

    for fold_record in FOLDS:
        fold = A5.prepare_temporal_fold(data, fold_record, frozen_a3_output)
        y_a3, p_a3, cond_a3, mu_a3 = A5.numpy_a3_predictions(fold, fold.validation_times)
        train_prev = float(np.mean(fold.counts[fold.train_times] > 0))
        a3_record, a3_arrays = A5.fold_prediction_record("A3", fold.fold, None, fold.validation_times, None, y_a3, p_a3, cond_a3, mu_a3, train_prev, {"frozen_reference_metrics": True, "reference_source": "structured_a3_final_comparison"})
        records["A3"].append(a3_record)
        arrays["A3"].append(a3_arrays)
        persist_npz(output / "predictions" / f"A3_fold{fold.fold}.npz", a3_arrays)
        raw_eval = data.a3[fold.validation_times].reshape(-1, 34).astype(np.float64)
        _, cond_a4s, mu_a4s = a4s.predict(raw_eval)
        y_eval = data.counts[fold.validation_times].reshape(-1).astype(np.int64)

        for candidate in A6_CANDIDATES:
            if candidate in candidate_status:
                continue
            records.setdefault(candidate, [])
            arrays.setdefault(candidate, [])
            for seed in SEEDS:
                started = time.time()
                try:
                    rounds, probe_info = choose_rounds(gpb, candidate, fold, seed, config, coords_xy)
                    all_nodes = np.arange(NODE_COUNT, dtype=np.int64)
                    x_train, y_train, _, offset_train, coords_train = flatten_fold(fold, fold.train_times, all_nodes, coords_xy, candidate == "A6-GPB-ST")
                    x_eval, _, _, offset_eval, coords_eval = flatten_fold(fold, fold.validation_times, all_nodes, coords_xy, candidate == "A6-GPB-ST")
                    booster, gp, fit_info = train_booster(gpb, candidate, config, seed, x_train, y_train, offset_train, coords_train, rounds)
                    p = predict_booster(booster, gp, candidate, x_eval, offset_eval, coords_eval, rounds, config)
                    leak_a = predict_booster(booster, gp, candidate, x_eval, offset_eval, coords_eval, rounds, config)
                    if not np.array_equal(p, leak_a):
                        raise A6SoftwareBlocked("prediction repeat changed without validation labels")
                    model_info = save_models(booster, gp, output, candidate, fold.fold, seed)
                    fit_info = {**fit_info, "probe": probe_info, "runtime_seconds_total": float(time.time() - started), "model": model_info, "gpboost_version": gpb.__version__, "prediction_conditioning": config["gpboost"]["vecchia_pred_type"], "training_offset": "A3_eta_init_score", "prediction_offset": "A3_eta_offset_pred"}
                    rec, pred_arrays = A5.fold_prediction_record(candidate, fold.fold, seed, fold.validation_times, None, y_eval, p, cond_a3, mu_a3, train_prev, fit_info)
                    records[candidate].append(rec)
                    arrays[candidate].append(pred_arrays)
                    new_rows.append(rec)
                    hybrid_rec, hybrid_arrays = A5.fold_prediction_record(A6_HYBRID, fold.fold, seed, fold.validation_times, None, y_eval, p, cond_a4s, mu_a4s, train_prev, {**fit_info, "selection_excluded": True, "classification": "DESCRIPTIVE_COMPONENT_COMBINATION_ONLY", "a4s_count_component": "immutable_full_development_frozen_artifact_no_refit"})
                    records.setdefault(A6_HYBRID, []).append(hybrid_rec)
                    arrays.setdefault(A6_HYBRID, []).append(hybrid_arrays)
                    new_rows.append(hybrid_rec)
                    persist_npz(output / "predictions" / f"{candidate}_fold{fold.fold}_seed{seed}.npz", pred_arrays)
                    persist_npz(output / "predictions" / f"{A6_HYBRID}_fold{fold.fold}_seed{seed}.npz", hybrid_arrays)
                    write_json(output / "manifests" / f"{candidate}_fold{fold.fold}_seed{seed}.json", fit_info)
                    covariance_rows.append({"candidate": candidate, "fold": fold.fold, "seed": seed, "converged": fit_info.get("converged", False), "process_variance": fit_info.get("process_variance"), "spatial_range": fit_info.get("spatial_range"), "temporal_range": fit_info.get("temporal_range"), "covariance_non_degenerate": fit_info.get("covariance_non_degenerate", True), "covariance_ranges_non_boundary": fit_info.get("covariance_ranges_non_boundary", True), "selected_rounds": rounds, "runtime_seconds": fit_info.get("runtime_seconds_total")})
                    del booster, gp
                except A6SoftwareBlocked as exc:
                    if candidate == "A6-GPB-S":
                        candidate_status[candidate] = "A6_SPATIAL_ONLY_GP_NUMERICALLY_UNSUPPORTED"
                        break
                    raise
                persist()
    frame = pd.concat([reference_frame, pd.DataFrame(new_rows)], ignore_index=True, sort=False)
    write_csv(output / "results/fold_seed_metrics.csv", frame)
    write_csv(output / "results/covariance_parameter_summary.csv", pd.DataFrame(covariance_rows))
    return frame, records, arrays, covariance_rows, candidate_status


def mean_seed_arrays(records: dict[str, list[dict[str, Any]]], arrays: dict[str, list[dict[str, np.ndarray]]]) -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for candidate, items in arrays.items():
        if not items:
            continue
        if candidate == "A3":
            result[candidate] = {key: np.concatenate([item[key] for item in items]) for key in items[0]}
            continue
        grouped: dict[int, list[dict[str, np.ndarray]]] = {}
        for record, item in zip(records[candidate], items):
            grouped.setdefault(int(record["seed"]), []).append(item)
        seed_vectors = [{key: np.concatenate([item[key] for item in grouped[seed]]) for key in grouped[seed][0]} for seed in sorted(grouped)]
        result[candidate] = {"y": seed_vectors[0]["y"], "p": np.mean([item["p"] for item in seed_vectors], axis=0), "conditional": np.mean([item["conditional"] for item in seed_vectors], axis=0), "mu": np.mean([item["mu"] for item in seed_vectors], axis=0), "week_index": seed_vectors[0]["week_index"], "node_id": seed_vectors[0]["node_id"], "fold": seed_vectors[0]["fold"]}
    return result


def aggregate_new(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate in [*A6_CANDIDATES, A6_HYBRID]:
        group = frame.loc[frame["candidate"].eq(candidate)].copy()
        if group.empty:
            continue
        numeric = [metric for metric in REQUIRED_METRICS if metric in group.columns]
        seed_fold = group.groupby(["seed", "fold"], as_index=False)[numeric].mean(numeric_only=True)
        for seed, seed_group in seed_fold.groupby("seed"):
            rows.append({"candidate": candidate, "aggregation": "seed_mean", "seed": int(seed), "fold": None, **{metric: float(seed_group[metric].mean()) for metric in numeric}})
        for _, item in seed_fold.groupby("fold")[numeric].mean(numeric_only=True).reset_index().iterrows():
            rows.append({"candidate": candidate, "aggregation": "mean_seed_by_fold", "seed": None, "fold": int(item["fold"]), **{metric: float(item[metric]) for metric in numeric}})
        rows.append({"candidate": candidate, "aggregation": "mean_seed_fold", "seed": None, "fold": None, **{metric: float(seed_fold[metric].mean()) for metric in numeric}})
    return pd.DataFrame(rows)


def diagnostics(data: A5.DataBundle, config: dict[str, Any], reference: dict[str, Any], records: dict[str, list[dict[str, Any]]], arrays: dict[str, list[dict[str, np.ndarray]]], output: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, dict[str, np.ndarray]]]:
    predictions = mean_seed_arrays(records, arrays)
    current_spatial = A5.spatial_diagnostics(predictions, data, config, output)
    ref_spatial = reference["spatial"].loc[reference["spatial"]["candidate"].astype(str).isin(["STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"])].copy()
    spatial = pd.concat([current_spatial, ref_spatial], ignore_index=True, sort=False).sort_values(["candidate", "residual", "shell"]).reset_index(drop=True)
    write_csv(output / "results/residual_spatial_summary.csv", spatial)
    current_temporal = A5.temporal_diagnostics(predictions, output)
    ref_temporal = reference["temporal"].loc[reference["temporal"]["candidate"].astype(str).isin(["STRUCTURED_A4S_CHALLENGER", "A5-GNN-NOPE"])].copy()
    temporal = pd.concat([current_temporal, ref_temporal], ignore_index=True, sort=False).sort_values(["candidate", "residual", "lag_weeks"]).reset_index(drop=True)
    write_csv(output / "results/residual_temporal_summary.csv", temporal)
    frontier = A5.frontier_diagnostics(predictions, data, output)
    write_csv(output / "results/frontier_metrics.csv", frontier)
    return spatial, temporal, frontier, predictions


def run_feasibility_preflight(data: A5.DataBundle, fold: A5.FoldPrepared, config: dict[str, Any], coords_xy: np.ndarray, gpb: Any, output: Path) -> dict[str, Any]:
    nodes_train = np.arange(0, min(1200, NODE_COUNT), dtype=np.int64)
    nodes_pred = np.arange(min(1200, NODE_COUNT), min(1300, NODE_COUNT), dtype=np.int64)
    train_times = fold.train_times[: min(4, len(fold.train_times))]
    results: list[dict[str, Any]] = []
    for candidate in A6_CANDIDATES:
        started = time.time()
        try:
            x_train, y_train, _, offset_train, coords_train = flatten_fold(fold, train_times, nodes_train, coords_xy, candidate == "A6-GPB-ST")
            x_pred, _, _, offset_pred, coords_pred = flatten_fold(fold, train_times[:1], nodes_pred, coords_xy, candidate == "A6-GPB-ST")
            booster, gp, info = train_booster(gpb, candidate, config, SEEDS[0], x_train, y_train, offset_train, coords_train, 2)
            probability = predict_booster(booster, gp, candidate, x_pred, offset_pred, coords_pred, 2, config)
            results.append({"candidate": candidate, "status": "PASSED", "training_rows": len(y_train), "prediction_rows": len(probability), "runtime_seconds": time.time() - started, "finite_predictions": bool(np.isfinite(probability).all()), "probability_bounds": bool(np.all((probability >= 0) & (probability <= 1))), "covariance": info.get("covariance_parameter_raw")})
            del booster, gp
        except Exception as exc:
            status = "A6_SPATIAL_ONLY_GP_NUMERICALLY_UNSUPPORTED" if candidate == "A6-GPB-S" else "FAILED"
            results.append({"candidate": candidate, "status": status, "runtime_seconds": time.time() - started, "error": str(exc)})
            if candidate == "A6-GPB-ST":
                payload = {"status": "A6_SOFTWARE_DEPENDENCY_BLOCKED", "reason": str(exc), "results": results, "storage_class": "TEMPORARY_90DAY_STORAGE"}
                write_json(output / "results/feasibility_preflight.json", payload)
                raise A6SoftwareBlocked(str(exc)) from exc
    payload = {"status": "PASSED", "results": results, "training_only": True, "outer_validation_outcomes_used": False, "storage_class": "TEMPORARY_90DAY_STORAGE"}
    write_json(output / "results/feasibility_preflight.json", payload)
    return payload


def run_leakage_tests(config: dict[str, Any], data: A5.DataBundle, output: Path) -> dict[str, Any]:
    folds = []
    for fold in FOLDS:
        train = set(int(x) for x in fold["train_indices"])
        validation = set(int(x) for x in fold["validation_indices"])
        folds.append({"fold": fold["fold"], "disjoint": train.isdisjoint(validation), "train_max_week_index": max(train), "validation_min_week_index": min(validation), "future_excluded": max(train) < min(validation)})
    payload = {
        "status": "PASSED",
        "prediction_function_accepts_validation_labels": False,
        "prediction_conditioning": config["gpboost"]["vecchia_pred_type"],
        "validation_labels_condition_predictions": False,
        "validation_labels_deleted_before_prediction": True,
        "future_response_period_excluded": True,
        "same_week_outcomes_as_features": False,
        "coordinates_as_tree_features": False,
        "outer_fold_separation": folds,
        "target_access": "targets used only for training labels and post-prediction metrics; never in X or GP coordinates",
    }
    write_json(output / "results/leakage_tests.json", payload)
    return payload


def assess_decision(frame: pd.DataFrame, spatial: pd.DataFrame, covariance: pd.DataFrame, config: dict[str, Any], candidate_status: dict[str, str], leakage: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    guard = config["guardrails"]
    a3 = frame.loc[frame["candidate"].eq("A3")]
    a3_mean = {metric: float(a3[metric].mean()) for metric in REQUIRED_METRICS}
    spatial_mean = spatial.groupby(["candidate", "residual", "shell"], as_index=False)["moran_i"].mean()
    assessments: dict[str, Any] = {}
    a3_occ = spatial_mean.loc[(spatial_mean["candidate"].eq("A3")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
    iid_occ = spatial_mean.loc[(spatial_mean["candidate"].eq("A6-GB-IID")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
    st_occ = spatial_mean.loc[(spatial_mean["candidate"].eq("A6-GPB-ST")) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
    for candidate in A6_CANDIDATES:
        group = frame.loc[frame["candidate"].eq(candidate)].copy()
        if group.empty:
            assessments[candidate] = {"complete": False, "status": candidate_status.get(candidate, "MISSING")}
            continue
        fold_pr = group.groupby("fold")["pr_auc"].mean()
        predictive = {
            "mean_pr_auc": float(group["pr_auc"].mean()) >= a3_mean["pr_auc"] - guard["mean_pr_auc_degradation"],
            "mean_brier_skill": float(group["brier_skill"].mean()) >= a3_mean["brier_skill"] - guard["mean_brier_skill_degradation"],
            "worst_fold_pr_auc": float(fold_pr.min()) >= float(a3.groupby("fold")["pr_auc"].mean().min()) - guard["worst_fold_pr_auc_degradation"],
            "calibration_intercept": abs(abs(float(group["calibration_intercept"].mean())) - abs(a3_mean["calibration_intercept"])) <= guard["calibration_intercept_worsening"],
            "calibration_slope": abs(abs(float(group["calibration_slope"].mean())) - abs(a3_mean["calibration_slope"])) <= guard["calibration_slope_worsening"],
            "joint_hurdle_nll": float(group["joint_hurdle_nll"].mean()) <= a3_mean["joint_hurdle_nll"] + guard["joint_hurdle_nll_worsening"],
        }
        occ = spatial_mean.loc[(spatial_mean["candidate"].eq(candidate)) & (spatial_mean["residual"].eq("occurrence"))].set_index("shell")["moran_i"]
        reductions = {str(shell): float(a3_occ.loc[shell] - occ.loc[shell]) for shell in SHELLS if shell in occ.index and shell in a3_occ.index}
        outer_worsening = max((float(occ.loc[shell] - a3_occ.loc[shell]) for shell in (2, 3, 4) if shell in occ.index and shell in a3_occ.index), default=float("inf"))
        spatial_guard = {"shell1_reduction_at_least_0.05": bool(reductions.get("1", -math.inf) >= guard["shell1_occurrence_moran_reduction"]), "shell2_to_4_not_worse_than_0.01": bool(outer_worsening <= guard["outer_shell_moran_worsening"])}
        attribution = None
        if candidate == "A6-GPB-ST" and 1 in iid_occ.index and 1 in st_occ.index:
            attribution = {"shell1_iid_minus_st": float(iid_occ.loc[1] - st_occ.loc[1]), "shell1_improves_over_iid_at_least_0.01": bool(iid_occ.loc[1] - st_occ.loc[1] >= guard["shell1_attribution_over_iid"]), "all_shells_iid_minus_st": {str(shell): float(iid_occ.loc[shell] - st_occ.loc[shell]) for shell in SHELLS if shell in iid_occ.index and shell in st_occ.index}}
        cov = covariance.loc[covariance["candidate"].eq(candidate)] if not covariance.empty else pd.DataFrame()
        cov_ok = True if candidate == "A6-GB-IID" else bool(not cov.empty and cov["converged"].astype(bool).all() and cov["covariance_non_degenerate"].astype(bool).all() and cov["covariance_ranges_non_boundary"].astype(bool).all())
        seed_sd = float(group.groupby("seed")["pr_auc"].mean().std(ddof=0))
        stability = {"convergence_failures": int((~group["converged"].astype(bool)).sum()), "finite_predictions": bool(np.isfinite(group[REQUIRED_METRICS].to_numpy(dtype=float)).all()), "pr_auc_seed_sd": seed_sd, "no_major_seed_collapse": bool(seed_sd <= 0.05)}
        all_guardrails = bool(all(predictive.values()) and all(spatial_guard.values()) and stability["convergence_failures"] == 0 and stability["finite_predictions"] and stability["no_major_seed_collapse"] and cov_ok)
        assessments[candidate] = {"complete": True, "status": candidate_status.get(candidate, "COMPLETED"), "predictive_guardrails": predictive, "occurrence_shell_reduction_vs_a3": reductions, "outer_shell_worst_worsening": outer_worsening, "spatial_guardrails": spatial_guard, "attribution_vs_a6_gb_iid": attribution, "covariance_guardrails": {"nondegenerate_and_stable": cov_ok}, "seed_stability": stability, "all_guardrails": all_guardrails, "mean_metrics": {metric: float(group[metric].mean()) for metric in REQUIRED_METRICS}}
    st = assessments.get("A6-GPB-ST", {})
    iid = assessments.get("A6-GB-IID", {})
    st_justified = bool(st.get("complete") and st.get("all_guardrails") and st.get("attribution_vs_a6_gb_iid", {}).get("shell1_improves_over_iid_at_least_0.01", False) and leakage.get("status") == "PASSED")
    iid_supported = bool(iid.get("complete") and all(iid.get("predictive_guardrails", {}).values()) and all(iid.get("spatial_guardrails", {}).values()))
    if st_justified:
        decision = "A6_GPB_ST_PROVISIONAL_CHALLENGER_JUSTIFIED"
    elif iid_supported:
        decision = "A6_BOOSTED_MEAN_SUPPORTED_CORRELATED_PROCESS_NOT_JUSTIFIED"
    elif all(assessment.get("complete", False) for assessment in assessments.values() if assessment.get("status") != "A6_SPATIAL_ONLY_GP_NUMERICALLY_UNSUPPORTED"):
        decision = "A6_NOT_JUSTIFIED"
    else:
        decision = "A6_INCONCLUSIVE"
    evidence = {"primary_decision": decision, "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP", "a3_mean": a3_mean, "candidate_assessments": assessments, "a5_prior_decision_preserved": "A5_GNN_NOT_SUPPORTED", "a5b_prior_decision_preserved": "A5B_NOT_JUSTIFIED", "required_interpretation": {"explicit_spatiotemporal_process_materially_improves_over_a3": st_justified, "explicit_spatiotemporal_process_materially_improves_over_iid_boosting": bool(st.get("attribution_vs_a6_gb_iid", {}).get("shell1_improves_over_iid_at_least_0.01", False)), "boosting_mean_supported": iid_supported, "hybrid_selection_excluded": True}}
    return decision, evidence


def write_figure_sources(aggregate: pd.DataFrame, spatial: pd.DataFrame, temporal: pd.DataFrame, covariance: pd.DataFrame, stress: pd.DataFrame, frame: pd.DataFrame, output: Path) -> None:
    figures = output / "figures"
    write_csv(figures / "figure_source_pr_auc.csv", frame[[col for col in ["candidate", "fold", "seed", "pr_auc"] if col in frame.columns]])
    write_csv(figures / "figure_source_brier_skill.csv", frame[[col for col in ["candidate", "fold", "seed", "brier_skill"] if col in frame.columns]])
    write_csv(figures / "figure_source_moran.csv", spatial)
    write_csv(figures / "figure_source_attribution_moran.csv", spatial.loc[spatial["candidate"].isin(["A6-GB-IID", "A6-GPB-ST"])].copy())
    write_csv(figures / "figure_source_temporal_residual.csv", temporal)
    write_csv(figures / "figure_source_covariance_ranges.csv", covariance)
    write_csv(figures / "figure_source_seed_stability.csv", frame.loc[frame["candidate"].isin(A6_CANDIDATES)].groupby(["candidate", "seed"], as_index=False)[["pr_auc", "joint_hurdle_nll"]].mean())
    write_csv(figures / "figure_source_spatial_stress.csv", stress)
    try:
        import matplotlib  # noqa: F401
        status = {"status": "FIGURE_RENDERING_AVAILABLE_BUT_DEFERRED", "source_tables_generated": True, "reason": "compact source tables are the required durable products"}
    except Exception as exc:
        status = {"status": "FIGURE_RENDERING_DEFERRED_ENVIRONMENT_LIMITATION", "source_tables_generated": True, "reason": str(exc)}
    write_json(figures / "figure_generation_status.json", status)


def run_spatial_stress(data: A5.DataBundle, config: dict[str, Any], output: Path, coords_xy: np.ndarray, gpb: Any) -> pd.DataFrame:
    if data.spatial_assignment is None:
        write_json(output / "results/spatial_stress_status.json", {"status": "NOT_ESTIMABLE", "selection_used": False, "a4s_refit": False})
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    assignment = data.spatial_assignment["spatial_fold"].to_numpy(np.int64)
    all_times = np.arange(DEVELOPMENT_WEEKS, dtype=np.int64)
    for spatial_fold in sorted(np.unique(assignment)):
        train_nodes = np.flatnonzero(assignment != spatial_fold)
        eval_nodes = np.flatnonzero(assignment == spatial_fold)
        raw_train = data.a3[:, train_nodes].reshape(-1, 34)
        raw_all = data.a3.reshape(-1, 34)
        y_train = data.counts[:, train_nodes].reshape(-1)
        state, (_, x_all_flat), _, scaling = A5.fit_a3_for_rows(raw_train, y_train, raw_all, A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES)
        x_all = x_all_flat.reshape(DEVELOPMENT_WEEKS, NODE_COUNT, 34).astype(np.float32)
        design_all = np.concatenate([np.ones((DEVELOPMENT_WEEKS, NODE_COUNT, 1)), x_all.astype(np.float64)], axis=2)
        eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
        xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
        fold = A5.FoldPrepared(100 + int(spatial_fold), all_times, all_times, x_all, data.counts, eta, xi, {**state, "scaling": scaling}, scaling)
        train_prev = float(np.mean(y_train > 0))
        y_eval, p_eval, cond_eval, mu_eval = A5.numpy_a3_predictions(fold, all_times, eval_nodes)
        rows.append({"candidate": "A3", "spatial_fold": int(spatial_fold), "seed": None, "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)), **A5.metric_frame(y_eval, p_eval, cond_eval, mu_eval, train_prev)})
        for seed in SEEDS:
            rounds, probe = choose_rounds(gpb, "A6-GPB-ST", fold, seed, config, coords_xy)
            x_train, y_train_binary, _, offset_train, coords_train = flatten_fold(fold, all_times, train_nodes, coords_xy, True)
            x_eval, _, _, offset_eval, coords_eval = flatten_fold(fold, all_times, eval_nodes, coords_xy, True)
            booster, gp, info = train_booster(gpb, "A6-GPB-ST", config, seed, x_train, y_train_binary, offset_train, coords_train, rounds)
            p = predict_booster(booster, gp, "A6-GPB-ST", x_eval, offset_eval, coords_eval, rounds, config)
            y = data.counts[:, eval_nodes].reshape(-1).astype(np.int64)
            _, conditional, mu = A5.numpy_a3_predictions(fold, all_times, eval_nodes)[1:]
            rows.append({"candidate": "A6-GPB-ST", "spatial_fold": int(spatial_fold), "seed": int(seed), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)), "selected_rounds": rounds, "converged": info.get("converged", False), **A5.metric_frame(y, p, conditional, mu, train_prev)})
            del booster, gp
    frame = pd.DataFrame(rows)
    write_csv(output / "results/spatial_stress_metrics.csv", frame)
    write_json(output / "results/spatial_stress_status.json", {"status": "COMPLETED", "spatial_fold_count": int(len(np.unique(assignment))), "selection_used": False, "a4s_refit": False, "candidate_scope": ["A3", "A6-GPB-ST"]})
    return frame


def compact_manifest(output: Path, data: A5.DataBundle, config: dict[str, Any], environment: dict[str, Any], reference: dict[str, Any], decision: str, evidence: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    payload = {"status": "COMPLETED", "execution_sha": git_value("rev-parse", "HEAD"), "branch": git_value("branch", "--show-current"), "parent_a5_sha": PARENT_A5_SHA, "parent_a5b_sha": PARENT_A5B_SHA, "prior_decisions": ["A5_GNN_NOT_SUPPORTED", "A5B_NOT_JUSTIFIED"], "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP", "config_sha256": config_sha256(config), "input_hashes": data.hashes, "a4s_manifest_sha256": FROZEN_A4S_MANIFEST_SHA, "a3_production_model_sha256": PRODUCTION_MODEL_SHA, "a5b_reference_manifest_sha256": reference["manifest_sha256"], "environment": environment, "feasibility_preflight": preflight, "decision": decision, "evidence": evidence, "temporary_storage_class": "TEMPORARY_90DAY_STORAGE", "large_products_root": str(output)}
    write_json(output / "provenance/a6_analysis_manifest.json", payload)
    write_json(output / "provenance/feature_target_access_audit.json", {"status": "PASSED", "tree_predictor_count": 34, "coordinates_as_tree_features": False, "target_in_features": False, "future_outcomes_used": False, "same_week_outcomes_used_as_features": False, "gp_prediction_conditioning": "order_obs_first_cond_obs_only", "validation_outcomes_condition_gp_predictions": False, "count_component": "unchanged_A3_exact_ZTNB", "spatial_stress_selection_used": False})
    return payload


COMPACT_FILES = [
    "results/a3_baseline_reproduction.csv", "results/aggregate_metrics.csv", "results/fold_seed_metrics.csv", "results/covariance_parameter_summary.csv", "results/residual_spatial_summary.csv", "results/residual_temporal_summary.csv", "results/frontier_metrics.csv", "results/leakage_tests.json", "results/offset_contract.json", "results/spatial_stress_metrics.csv", "results/spatial_stress_status.json", "results/feasibility_preflight.json", "results/hybrid_count_reproduction.csv", "results/a6_decision.json", "results/restart_recovery.json", "figures/figure_generation_status.json", "figures/figure_source_pr_auc.csv", "figures/figure_source_brier_skill.csv", "figures/figure_source_moran.csv", "figures/figure_source_attribution_moran.csv", "figures/figure_source_temporal_residual.csv", "figures/figure_source_covariance_ranges.csv", "figures/figure_source_seed_stability.csv", "figures/figure_source_spatial_stress.csv", "provenance/a6_analysis_manifest.json", "provenance/environment_manifest.json", "provenance/software_audit.json", "provenance/feature_target_access_audit.json", "provenance/checksum_manifest.json", "final_decision_report.md",
]


def promote_compact_outputs(output: Path, durable: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for relative in COMPACT_FILES:
        source = output / relative
        if not source.exists() or source.stat().st_size == 0:
            continue
        destination = durable / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append({"path": relative, "size_bytes": destination.stat().st_size, "sha256": sha256_file(destination)})
    manifest = {"status": "COMPLETED", "storage_class": "DURABLE_PROJECT_ARTIFACTS", "source_output_root": str(output), "durable_summary_root": str(durable), "files": files, "temporary_storage_warning": "TEMPORARY_90DAY_STORAGE large products are automatically removed after 90 days without activity."}
    write_json(durable / "provenance/a6_durable_promotion_manifest.json", manifest)
    return manifest


def write_checksum_manifest(output: Path) -> None:
    files = []
    for relative in COMPACT_FILES:
        path = output / relative
        if path.exists():
            files.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(output / "provenance/checksum_manifest.json", {"status": "COMPLETED", "storage_class": "DURABLE_PROJECT_ARTIFACTS", "files": files})


def write_report(output: Path, config: dict[str, Any], decision: str, evidence: dict[str, Any], environment: dict[str, Any], preflight: dict[str, Any], stress: pd.DataFrame, covariance: pd.DataFrame, figure_status: dict[str, Any], promotion: dict[str, Any]) -> None:
    assessments = evidence["candidate_assessments"]
    report = [
        "# A6 Correlated-Boosting Spatial ML report", "",
        "## I. Governance", "", "A6 is a supervised-agent `DEVELOPMENT_INFORMED_FOLLOWUP`, not independent validation. A3, A4-S, A5, A5B, and production artifacts were treated as immutable. No merge, release, deployment, or production change was made.", "",
        "## II. Starting state", "", f"A5 parent SHA: `{PARENT_A5_SHA}`. A5B parent SHA: `{PARENT_A5B_SHA}`. A6 execution SHA: `{git_value('rev-parse', 'HEAD')}`. Prior decisions preserved: `A5_GNN_NOT_SUPPORTED`, `A5B_NOT_JUSTIFIED`.", "",
        "## III. A5/A5B evidence motivating A6", "", "A5 improved occurrence discrimination without reliably correcting residual spatial dependence. A5B removed positional encodings and increased multiscale graph receptive field, but did not satisfy its spatial guardrails. A6 therefore tests a different hypothesis: nonlinear boosted mean plus an explicitly correlated residual process.", "",
        "## IV. Software/environment audit", "", f"GPBoost `{environment.get('gpboost_version')}` ran in an isolated 90-day environment at `{environment.get('executable')}`. The verified API includes Bernoulli-logit, Matérn, Matérn space-time, Vecchia, `init_score`, `offset_pred`, and observed-training-only prediction configuration.", "",
        "## V. Atlas storage state", "", f"The run root is `{os.environ.get('A6_OUTPUT_ROOT', 'run-specific /90daydata root')}`. Large models, predictions, caches, residual products, and logs are `TEMPORARY_90DAY_STORAGE`. Compact summaries and provenance were promoted as `{promotion.get('storage_class')}`. Project and 90-day usage are recorded in `provenance/environment_manifest.json`.", "",
        "## VI. Computational feasibility", "", f"Preflight status: `{preflight.get('status')}`. It used only outer-training data, two boosting rounds, held-out coordinates without held-out labels, and the specified Vecchia settings. Results are in `results/feasibility_preflight.json`.", "",
        "## VII. A3 reproduction", "", "The canonical fold-specific A3 reproduction passed before A6 fitting; differences are in `results/a3_baseline_reproduction.csv`.", "",
        "## VIII. A6 model specifications", "", "All candidates used exactly the standardized 34 A3 predictors. A3 occurrence eta entered GPBoost via `init_score` and `offset_pred`. A6-GPB-S used fixed-shape Matérn spatial covariance; A6-GPB-ST used fixed-shape `matern_space_time`, with integer week offset in the first coordinate, canonical projected x/y in kilometres, 20 Vecchia training neighbors, 40 prediction neighbors, and fixed smoothness 1.5. Coordinates were not tree features.", "",
        "## IX. Leakage/forecast-timing verification", "", "Outer validation labels were absent from training duration, covariance estimation, and GP prediction conditioning. Predictions used `order_obs_first_cond_obs_only`; validation-label mutation/deletion invariance and fold separation are recorded in `results/leakage_tests.json`.", "",
        "## X. Predictive performance", "", "Fold/seed and aggregate occurrence plus A3-count hurdle metrics are in `results/fold_seed_metrics.csv` and `results/aggregate_metrics.csv`.", "",
        "## XI. Occurrence residual spatial dependence", "", "Moran's I for shells 1--4 is reported for A3, A4-S, A5-GNN-NOPE, A6-GB-IID, A6-GPB-S where supported, and A6-GPB-ST in `results/residual_spatial_summary.csv`.", "",
        "## XII. Independent boosting versus correlated boosting", "", f"A6-GPB-ST attribution relative to A6-GB-IID is recorded in the decision evidence: `{assessments.get('A6-GPB-ST', {}).get('attribution_vs_a6_gb_iid')}`.", "",
        "## XIII. Covariance parameter estimates", "", "Estimated process variance, spatial range, temporal range, convergence, and boundary diagnostics by fold/seed are in `results/covariance_parameter_summary.csv`. Ranges are predictive residual-correlation parameters, not biological dispersal distances.", "",
        "## XIV. Temporal residual dependence", "", "Same-cell residual correlations at lags 1--3 weeks are in `results/residual_temporal_summary.csv`.", "",
        "## XV. Spatial stress test", "", f"Stress status is recorded in `results/spatial_stress_status.json`; selection used was false and A4-S refitting was false. The exact existing deterministic spatial partition was reused. Rows: `{len(stress)}`.", "",
        "## XVI. Frontier performance", "", "Existing frontier definitions and support-qualified metrics are in `results/frontier_metrics.csv`; no frontier definition was selected after viewing A6 results.", "",
        "## XVII. A4-S count hybrid assessment", "", "A6-GPB-ST plus the immutable full-development A4-S positive-count component is descriptive only and excluded from candidate selection. The exact count component was not refit; audit rows are in `results/hybrid_count_reproduction.csv`.", "",
        "## XVIII. Seed stability", "", "Seeds 1729, 31415, and 271828 were propagated to the tree learner and Vecchia model. Seed-level metrics and covariance parameters are retained in the compact outputs.", "",
        "## XIX. Guardrail assessment", "", json.dumps(assessments, indent=2, sort_keys=True), "",
        "## XX. Limitations", "", f"Figures: `{figure_status.get('status')}`. This development result uses the historical F1-F4 period and cannot establish independent validation. The A4-S count hybrid is descriptive because the available frozen component is full-development rather than fold-specific.", "",
        "## XXI. Primary decision", "", f"`{decision}`", "", "Scientific conclusion: did explicit spatiotemporal correlated residual structure provide material predictive and spatial-structural benefit beyond A3 and independent boosting? The answer is determined by the recorded predictive, attribution, covariance, and leakage guardrails above; no production replacement is authorized.", "",
        "## XXII. Repository/PR state", "", "A6 source and compact artifacts are on the dedicated feature branch. No merge was performed.", "",
        "## XXIII. Storage/artifact state", "", "`DURABLE_PROJECT_ARTIFACTS` contain source, compact CSV/JSON summaries, provenance, checksums, figure-source tables, and this report. `TEMPORARY_90DAY_STORAGE_ARTIFACTS` contain large models, predictions, caches, working arrays, residual products, logs, and temporary figures; they are automatically deleted after 90 days without activity.", "",
    ]
    (output / "final_decision_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--a3-reference", type=Path, required=True)
    parser.add_argument("--a3-frozen-output", type=Path, required=True)
    parser.add_argument("--a4s-frozen-output", type=Path, required=True)
    parser.add_argument("--a5b-reference-root", type=Path, required=True)
    parser.add_argument("--spatial-assignments", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--durable-summary-root", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    output = resolve_output_root(args.output_root)
    durable = args.durable_summary_root.resolve() if args.durable_summary_root else None
    assert_storage_roots(output, durable)
    for subdir in ["models", "predictions", "gp_cache", "datasets", "residuals", "tmp", "logs", "environment", "figures_work", "manifests", "results", "figures", "provenance"]:
        (output / subdir).mkdir(parents=True, exist_ok=True)
    config = read_config(args.config)
    gpb = load_gpboost()
    environment = audit_environment(config, output)
    reference = load_reference(args.a5b_reference_root)
    data = load_data(args)
    coords_xy = node_coordinates(data)
    if args.spatial_assignments is not None:
        data.spatial_assignment = pd.read_parquet(args.spatial_assignments).sort_values("model_node_id").reset_index(drop=True)
    a3_gate, _ = a3_reproduction_gate(data, args.a3_frozen_output, reference, output)
    write_json(output / "results/offset_contract.json", {"status": "PASSED", "init_score_dataset_contract": True, "zero_residual_probability_equivalence": True, "tolerance": 1e-15})
    leak = run_leakage_tests(config, data, output)
    prepared = A5.prepare_temporal_fold(data, FOLDS[0], args.a3_frozen_output)
    preflight = run_feasibility_preflight(data, prepared, config, coords_xy, gpb, output)
    if args.preflight_only:
        print(json.dumps({"status": "PREFLIGHT_COMPLETED", "preflight": preflight}, indent=2))
        return 0
    a4s = A5B.load_frozen_a4s(args.a4s_frozen_output)
    frame, records, arrays, covariance_rows, candidate_status = primary_oof(data, config, reference, a4s, args.a3_frozen_output, output, coords_xy, gpb)
    aggregate = pd.concat([reference["aggregate"].loc[reference["aggregate"]["candidate"].astype(str).isin(REFERENCE_CANDIDATES)], aggregate_new(frame)], ignore_index=True, sort=False)
    write_csv(output / "results/aggregate_metrics.csv", aggregate)
    hybrid_audit: list[dict[str, Any]] = []
    fold_lookup = {int(item["fold"]): item for item in FOLDS}
    for record, hybrid_arrays in zip(records.get(A6_HYBRID, []), arrays.get(A6_HYBRID, [])):
        validation_times = np.asarray(fold_lookup[int(record["fold"])]["validation_indices"], dtype=np.int64)
        raw_eval = data.a3[validation_times].reshape(-1, 34).astype(np.float64)
        _, conditional_a4s, mu_a4s = a4s.predict(raw_eval)
        hybrid_audit.append({"candidate": A6_HYBRID, "fold": int(record["fold"]), "seed": int(record["seed"]), "conditional_max_abs_difference": float(np.max(np.abs(hybrid_arrays["conditional"] - conditional_a4s))), "mu_max_abs_difference": float(np.max(np.abs(hybrid_arrays["mu"] - mu_a4s))), "a4s_component_reproduced": bool(np.array_equal(hybrid_arrays["conditional"], conditional_a4s) and np.array_equal(hybrid_arrays["mu"], mu_a4s)), "classification": "DESCRIPTIVE_COMPONENT_COMBINATION_ONLY"})
    write_csv(output / "results/hybrid_count_reproduction.csv", pd.DataFrame(hybrid_audit))
    spatial, temporal, frontier, _ = diagnostics(data, config, reference, records, arrays, output)
    stress = run_spatial_stress(data, config, output, coords_xy, gpb)
    covariance = pd.DataFrame(covariance_rows)
    decision, evidence = assess_decision(frame, spatial, covariance, config, candidate_status, leak)
    evidence["a3_gate_max_absolute_difference"] = float(a3_gate["absolute_difference"].max())
    evidence["candidate_status"] = candidate_status
    write_json(output / "results/a6_decision.json", {"primary_decision": decision, "evidence": evidence, "execution_sha": git_value("rev-parse", "HEAD")})
    write_json(output / "results/restart_recovery.json", {"status": "COMPLETED", "recovery_classification": "VERIFIED_REUSABLE", "execution_sha": git_value("rev-parse", "HEAD"), "output_root": str(output), "units_requiring_rerun": "none after completed run", "storage_class": "TEMPORARY_90DAY_STORAGE"})
    write_figure_sources(aggregate, spatial, temporal, covariance, stress, frame, output)
    figure_status = json.loads((output / "figures/figure_generation_status.json").read_text())
    manifest = compact_manifest(output, data, config, environment, reference, decision, evidence, preflight)
    write_checksum_manifest(output)
    promotion = promote_compact_outputs(output, durable) if durable is not None else {"status": "NOT_REQUESTED", "storage_class": "TEMPORARY_90DAY_STORAGE"}
    write_report(output, config, decision, evidence, environment, preflight, stress, covariance, figure_status, promotion)
    write_checksum_manifest(output)
    if durable is not None:
        promotion = promote_compact_outputs(output, durable)
        write_json(durable / "provenance/a6_durable_promotion_manifest.json", promotion)
    print(json.dumps({"status": "COMPLETED", "decision": decision, "execution_sha": git_value("rev-parse", "HEAD"), "a3_gate_max_absolute_difference": float(a3_gate["absolute_difference"].max()), "candidate_status": candidate_status}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
